"""
PS5 Archive Handler
Handles compressed archives for PS5 backporting.
Supports ZIP, TAR variants natively via Python stdlib.
"""

import os
import sys
import re
import zipfile
import tarfile
import shutil
import fnmatch
import subprocess
import tempfile
import getpass
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Union


class ArchiveHandler:
    """
    Handle compressed archives for PS5 backporting.
    Supports ZIP, TAR variants natively via Python stdlib.
    Can optionally use external tools for 7z/RAR if available.
    """
    
    # Standard library supported formats
    NATIVE_FORMATS = {
        '.zip': 'zipfile',
        '.tar': 'tarfile',
        '.tar.gz': 'tarfile',
        '.tgz': 'tarfile',
        '.tar.bz2': 'tarfile',
        '.tbz2': 'tarfile',
        '.tar.xz': 'tarfile',
        '.txz': 'tarfile',
    }
    
    # Formats requiring external tools
    EXTERNAL_FORMATS = {
        '.7z': {'tool': '7z'},
        '.rar': {'tool': 'unrar', 'alt_tool': 'rar'},
    }
    
    # PS5 file patterns we want to extract
    PS5_FILE_PATTERNS = [
        'eboot.bin',
        '*.self',
        '*.prx',
        '*.elf',
        '*.sprx',
    ]

    @classmethod
    def _is_password_error(cls, error_msg: str) -> bool:
        """Check if an error message indicates a password issue."""
        if not error_msg:
            return False
        lower = error_msg.lower()
        return any(kw in lower for kw in [
            'wrong password', 'bad password', 'encrypted', 
            'password required', 'crc failed', 'checksum error',
            'password is incorrect'
        ])
    
    @classmethod
    def get_archive_info(cls, file_path: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Get archive information.
        Returns: (extension, handler_type, tool_name) 
                 handler_type is 'native', 'external', 'multipart_wrong_part', or None
        """
        if not file_path.exists() or not file_path.is_file():
            return None, None, None
        
        name_lower = file_path.name.lower()
        
        # 1. Check for multipart archives FIRST
        base_ext, is_first_part = cls._check_multipart(name_lower)
        if base_ext:
            if not is_first_part:
                info = cls.EXTERNAL_FORMATS.get(base_ext, {})
                tool = cls._find_external_tool(info.get('tool'), info.get('alt_tool'))
                return file_path.suffix.lower(), 'multipart_wrong_part', tool
            
            if base_ext in cls.EXTERNAL_FORMATS:
                info = cls.EXTERNAL_FORMATS[base_ext]
                tool = cls._find_external_tool(info['tool'], info.get('alt_tool'))
                return file_path.suffix.lower(), 'external' if tool else 'unsupported', tool
            else:
                return file_path.suffix.lower(), 'unsupported', None
        
        # 2. Check standard files
        all_extensions = sorted(
            list(cls.NATIVE_FORMATS.keys()) + list(cls.EXTERNAL_FORMATS.keys()),
            key=len,
            reverse=True
        )
        
        for ext in all_extensions:
            if name_lower.endswith(ext):
                if ext in cls.NATIVE_FORMATS:
                    return ext, 'native', cls.NATIVE_FORMATS[ext]
                else:
                    info = cls.EXTERNAL_FORMATS[ext]
                    tool = cls._find_external_tool(info['tool'], info.get('alt_tool'))
                    return ext, 'external' if tool else 'unsupported', tool
        
        return None, None, None
    
    @classmethod
    def _check_multipart(cls, name_lower: str) -> Tuple[Optional[str], bool]:
        """Check if a filename is part of a multipart archive."""
        m = re.search(r'\.part(\d+)\.rar$', name_lower)
        if m:
            return '.rar', int(m.group(1)) == 1
        
        m = re.search(r'\.r(\d+)$', name_lower)
        if m:
            return '.rar', False
        
        m = re.search(r'\.7z\.(\d+)$', name_lower)
        if m:
            return '.7z', int(m.group(1)) == 1
            
        m = re.search(r'\.zip\.(\d+)$', name_lower)
        if m:
            return '.zip', int(m.group(1)) == 1
            
        return None, False
    
    @classmethod
    def is_archive(cls, file_path: Path) -> bool:
        """Check if file is a recognized archive."""
        ext, handler_type, _ = cls.get_archive_info(file_path)
        return handler_type in ('native', 'external')
    
    @classmethod
    def is_natively_supported(cls, file_path: Path) -> bool:
        """Check if archive is supported by Python stdlib."""
        _, handler_type, _ = cls.get_archive_info(file_path)
        return handler_type == 'native'
    
    @classmethod
    def _find_external_tool(cls, tool_name: str, alt_tool: str = None) -> Optional[str]:
        """Find external tool in PATH."""
        for tool in [tool_name, alt_tool]:
            if tool is None:
                continue
            try:
                subprocess.run(
                    [tool] if tool == '7z' else [tool, '--help'],
                    capture_output=True,
                    timeout=5
                )
                return tool
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return None
    
    @classmethod
    def _matches_patterns(cls, filepath: str, patterns: List[str]) -> bool:
        """Check if filepath matches any of the patterns."""
        filename = Path(filepath).name.lower()
        return any(fnmatch.fnmatch(filename, p.lower()) for p in patterns)
    
    @classmethod
    def _detect_file_type_from_name(cls, filepath: str) -> str:
        """Detect if file is likely SELF or ELF based on name."""
        name = Path(filepath).name.lower()
        if name.endswith('.self') or name.endswith('.prx') or name.endswith('.sprx'):
            return 'self'
        elif name.endswith('.elf'):
            return 'elf'
        elif name == 'eboot.bin':
            return 'unknown_binary'
        return 'other'
    
    @classmethod
    def list_target_files(
        cls,
        archive_path: Path,
        patterns: List[str] = None,
        password: str = None,
        verbose: bool = False
    ) -> List[Dict[str, Any]]:
        """List files in archive that match target patterns."""
        if patterns is None:
            patterns = cls.PS5_FILE_PATTERNS
        
        ext, handler_type, tool = cls.get_archive_info(archive_path)
        if ext is None:
            return []
        
        if handler_type == 'native':
            return cls._list_native_files(archive_path, ext, patterns, password, verbose)
        elif handler_type == 'external' and tool:
            return cls._list_external_files(archive_path, ext, tool, patterns, password, verbose)
        else:
            return []
    
    @classmethod
    def _list_native_files(
        cls,
        archive_path: Path,
        ext: str,
        patterns: List[str],
        password: str,
        verbose: bool
    ) -> List[Dict[str, Any]]:
        """List files from natively supported archives."""
        files = []
        pwd_bytes = password.encode() if password else None
        
        try:
            if ext == '.zip':
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    for info in zf.infolist():
                        if not info.is_dir() and cls._matches_patterns(info.filename, patterns):
                            # Test if we can read the header (catches encrypted files if no pwd)
                            try:
                                if pwd_bytes:
                                    zf.read(info.filename, pwd=pwd_bytes)
                                else:
                                    # Just check name match, delay actual read error to extraction
                                    pass 
                                
                                files.append({
                                    'path': info.filename,
                                    'size': info.file_size,
                                    'compressed_size': info.compress_size,
                                    'detected_type': cls._detect_file_type_from_name(info.filename)
                                })
                            except RuntimeError:
                                # If we hit here, it's encrypted and we don't have the right/no pwd
                                return [{'path': '__PASSWORD_REQUIRED__', 'size': 0, 'detected_type': 'error'}]
            
            elif ext.startswith('.tar') or ext in ('.tgz', '.tbz2', '.txz'):
                mode = 'r'
                if '.gz' in ext or ext == '.tgz': mode = 'r:gz'
                elif '.bz2' in ext or ext == '.tbz2': mode = 'r:bz2'
                elif '.xz' in ext or ext == '.txz': mode = 'r:xz'
                
                with tarfile.open(archive_path, mode) as tf:
                    for member in tf.getmembers():
                        if member.isfile() and cls._matches_patterns(member.name, patterns):
                            files.append({
                                'path': member.name,
                                'size': member.size,
                                'detected_type': cls._detect_file_type_from_name(member.name)
                            })
        
        except Exception as e:
            if verbose:
                print(f"Error listing archive: {e}")
        
        return files
    
    @classmethod
    def _list_external_files(
        cls,
        archive_path: Path,
        ext: str,
        tool: str,
        patterns: List[str],
        password: str,
        verbose: bool
    ) -> List[Dict[str, Any]]:
        """List files from archives requiring external tools."""
        files = []
        
        try:
            # Base command WITHOUT -p to prevent stdin freeze
            if tool == '7z':
                list_cmd = [tool, 'l', '-slt', str(archive_path)]
            else:  
                list_cmd = [tool, 'lb', str(archive_path)]
            
            # ONLY append -p if a password was actually provided by the user
            if password:
                list_cmd.append(f'-p{password}')
            
            result = subprocess.run(list_cmd, capture_output=True, text=True, timeout=120)
            
            # Combine stdout and stderr. Some unrar versions dump the file list into stderr!
            output = result.stdout + "\n" + result.stderr
            
            # If unrar/7z completely fails to list anything, check if it's a password issue
            if result.returncode != 0 and not output.strip():
                if cls._is_password_error(result.stderr):
                    return [{'path': '__PASSWORD_REQUIRED__', 'size': 0, 'detected_type': 'error'}]
            
            # Parse the combined output
            if tool == '7z':
                for line in output.split('\n'):
                    if line.startswith('Path = '):
                        filepath = line[7:].strip()
                        if filepath and cls._matches_patterns(filepath, patterns):
                            files.append({'path': filepath, 'size': 0, 'detected_type': cls._detect_file_type_from_name(filepath)})
            else:
                # unrar bare list format (one path per line)
                for line in output.split('\n'):
                    filepath = line.strip()
                    if filepath and cls._matches_patterns(filepath, patterns):
                        files.append({'path': filepath, 'size': 0, 'detected_type': cls._detect_file_type_from_name(filepath)})
        
        except Exception as e:
            if verbose:
                print(f"Error listing archive with {tool}: {e}")
        
        return files
    
    @classmethod
    def extract_files(
        cls,
        archive_path: Path,
        output_dir: Path,
        patterns: List[str] = None,
        preserve_structure: bool = True,
        password: str = None,
        verbose: bool = True
    ) -> Dict[str, Any]:
        """Extract files matching patterns from archive."""
        if patterns is None:
            patterns = cls.PS5_FILE_PATTERNS
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        ext, handler_type, tool = cls.get_archive_info(archive_path)
        
        result = {
            'archive': str(archive_path),
            'extension': ext,
            'handler_type': handler_type,
            'output_dir': str(output_dir),
            'extracted_files': [],
            'skipped_files': [],
            'errors': [],
            'success': False,
            'is_password_error': False  # Flag to trigger retry logic
        }
        
        if handler_type is None:
            result['errors'].append(f"Unsupported archive format: {ext or 'unknown'}")
            return result
        
        if handler_type == 'unsupported':
            result['errors'].append(f"Archive format '{ext}' requires external tool.")
            return result
        
        try:
            if handler_type == 'native':
                result = cls._extract_native(archive_path, ext, output_dir, patterns, preserve_structure, password, verbose, result)
            elif handler_type == 'external':
                result = cls._extract_external(archive_path, ext, tool, output_dir, patterns, preserve_structure, password, verbose, result)
            
            result['success'] = len(result['extracted_files']) > 0
            
        except Exception as e:
            err_str = str(e)
            result['errors'].append(f"Extraction error: {err_str}")
            if cls._is_password_error(err_str):
                result['is_password_error'] = True
            if verbose:
                print(f"Error: {e}")
        
        return result
    
    @classmethod
    def _extract_native(
        cls,
        archive_path: Path,
        ext: str,
        output_dir: Path,
        patterns: List[str],
        preserve_structure: bool,
        password: str,
        verbose: bool,
        result: Dict
    ) -> Dict:
        """Extract from natively supported archives."""
        if ext == '.zip':
            return cls._extract_zip(archive_path, output_dir, patterns, preserve_structure, password, verbose, result)
        elif ext.startswith('.tar') or ext in ('.tgz', '.tbz2', '.txz'):
            return cls._extract_tar(archive_path, ext, output_dir, patterns, preserve_structure, password, verbose, result)
        return result
    
    @classmethod
    def _extract_zip(
        cls,
        archive_path: Path,
        output_dir: Path,
        patterns: List[str],
        preserve_structure: bool,
        password: str,
        verbose: bool,
        result: Dict
    ) -> Dict:
        """Extract files from ZIP archive."""
        pwd_bytes = password.encode() if password else None
        
        with zipfile.ZipFile(archive_path, 'r') as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                
                if not cls._matches_patterns(info.filename, patterns):
                    result['skipped_files'].append(info.filename)
                    continue
                
                out_path = output_dir / info.filename if preserve_structure else output_dir / Path(info.filename).name
                
                try:
                    out_path.resolve().relative_to(output_dir.resolve())
                except ValueError:
                    result['errors'].append(f"Skipping (path traversal): {info.filename}")
                    continue
                
                out_path.parent.mkdir(parents=True, exist_ok=True)
                
                try:
                    with zf.open(info, pwd=pwd_bytes) as src, open(out_path, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    
                    result['extracted_files'].append({
                        'archive_path': info.filename,
                        'output_path': str(out_path),
                        'size': info.file_size
                    })
                    if verbose:
                        print(f"  Extracted: {info.filename if preserve_structure else out_path.name}")
                
                except RuntimeError as e:
                    # Catch specific ZIP password errors
                    if cls._is_password_error(str(e)):
                        result['is_password_error'] = True
                        result['errors'].append(str(e))
                        return result # Halt extraction immediately to allow password retry
                    result['errors'].append(f"Error extracting {info.filename}: {e}")
        
        return result
    
    @classmethod
    def _extract_tar(
        cls,
        archive_path: Path,
        ext: str,
        output_dir: Path,
        patterns: List[str],
        preserve_structure: bool,
        password: str,
        verbose: bool,
        result: Dict
    ) -> Dict:
        """Extract files from TAR archive."""
        mode = 'r'
        if '.gz' in ext or ext == '.tgz': mode = 'r:gz'
        elif '.bz2' in ext or ext == '.tbz2': mode = 'r:bz2'
        elif '.xz' in ext or ext == '.txz': mode = 'r:xz'
        
        with tarfile.open(archive_path, mode) as tf:
            for member in tf.getmembers():
                if not member.isfile(): continue
                if not cls._matches_patterns(member.name, patterns):
                    result['skipped_files'].append(member.name)
                    continue
                
                out_path = output_dir / member.name if preserve_structure else output_dir / Path(member.name).name
                
                try:
                    out_path.resolve().relative_to(output_dir.resolve())
                except ValueError:
                    result['errors'].append(f"Skipping (path traversal): {member.name}")
                    continue
                
                out_path.parent.mkdir(parents=True, exist_ok=True)
                
                try:
                    with tf.extractfile(member) as src:
                        if src is None: continue
                        with open(out_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                    
                    result['extracted_files'].append({'archive_path': member.name, 'output_path': str(out_path), 'size': member.size})
                    if verbose:
                        print(f"  Extracted: {member.name if preserve_structure else out_path.name}")
                except Exception as e:
                    result['errors'].append(f"Error extracting {member.name}: {e}")
        return result
    
    @classmethod
    def _extract_external(
        cls,
        archive_path: Path,
        ext: str,
        tool: str,
        output_dir: Path,
        patterns: List[str],
        preserve_structure: bool,
        password: str,
        verbose: bool,
        result: Dict
    ) -> Dict:
        """Extract using external tools."""
        try:
            target_files = cls._list_external_files(archive_path, ext, tool, patterns, password, verbose=False)
            
            if not target_files:
                result['errors'].append("No matching files found or cannot read archive contents.")
                return result
            
            if target_files[0].get('path') == '__PASSWORD_REQUIRED__':
                result['is_password_error'] = True
                result['errors'].append("Archive is password protected.")
                return result

            file_paths_to_extract = [f['path'] for f in target_files]
            
            # Build command safely WITHOUT -p initially
            cmd = []
            if tool == '7z':
                cmd = [tool, 'x', '-y']
                if password:
                    cmd.append(f'-p{password}')
                cmd.extend([f'-o{output_dir}', str(archive_path)] + file_paths_to_extract)
            else:  
                cmd = [tool, 'x', '-y']
                if password:
                    cmd.append(f'-p{password}')
                cmd.extend([str(archive_path)] + file_paths_to_extract + [f'{output_dir}/'])
            
            if verbose:
                print(f"  Extracting {len(file_paths_to_extract)} specific file(s)...")
            
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            # Check if extraction failed due to password
            if proc.returncode != 0:
                err_output = proc.stderr + proc.stdout
                if cls._is_password_error(err_output):
                    result['is_password_error'] = True
                    result['errors'].append("Wrong password or archive is encrypted.")
                    return result
            
            # Verify which files were actually written
            for f in target_files:
                out_path = output_dir / f['path'] if preserve_structure else output_dir / Path(f['path']).name
                
                if out_path.exists():
                    result['extracted_files'].append({'archive_path': f['path'], 'output_path': str(out_path), 'size': out_path.stat().st_size})
                    if verbose:
                        print(f"  Extracted: {f['path'] if preserve_structure else out_path.name}")
                else:
                    result['skipped_files'].append(f['path'])
            
            if proc.returncode != 0 and not result['extracted_files']:
                err_msg = (proc.stderr + proc.stdout)[:500]
                result['errors'].append(f"{tool} failed: {err_msg}")
                
        except subprocess.TimeoutExpired:
            result['errors'].append("Extraction timed out.")
        except Exception as e:
            result['errors'].append(f"Error during extraction: {str(e)}")
        
        return result


def extract_archive_to_temp(
    archive_path: Union[str, Path],
    patterns: List[str] = None,
    verbose: bool = True,
    provided_password: str = None
) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
    """
    Extract archive to a temporary directory. Includes retry logic for passwords.
    """
    archive_path = Path(archive_path)
    
    if not ArchiveHandler.is_archive(archive_path):
        return None, {'success': False, 'errors': [f'Not a supported archive: {archive_path}']}
    
    ext, handler_type, tool = ArchiveHandler.get_archive_info(archive_path)
    
    if verbose:
        print(f"\n[Archive] Detected compressed file: {archive_path.name}")
        print(f"[Archive] Format: {ext} ({handler_type})")
    
    temp_dir = Path(tempfile.mkdtemp(prefix='ps5_archive_'))
    password = provided_password
    max_attempts = 3
    
    for attempt in range(max_attempts):
        # 1. List files (to show user what we found)
        target_files = ArchiveHandler.list_target_files(archive_path, patterns, password=password, verbose=False)
        
        # Handle list-level password requirement
        if target_files and target_files[0].get('path') == '__PASSWORD_REQUIRED__':
            if attempt < max_attempts - 1:
                if verbose:
                    print("[Archive] Archive is password protected.")
                password = _prompt_for_password(attempt > 0) # prompt if wrong pwd
                if password is None: break # User canceled
                continue
            else:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return None, {'success': False, 'errors': ['Maximum password attempts reached.']}
        
        if verbose:
            print(f"[Archive] Found {len(target_files)} target file(s) to extract")
            for f in target_files[:5]:
                print(f"         • {f['path']}")
            if len(target_files) > 5:
                print(f"         ... and {len(target_files) - 5} more")
        
        if not target_files:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None, {'success': False, 'errors': ['No target files found in archive']}
        
        # 2. Extract files
        if verbose:
            print(f"[Archive] Extracting to temporary directory...")
        
        result = ArchiveHandler.extract_files(
            archive_path=archive_path,
            output_dir=temp_dir,
            patterns=patterns,
            preserve_structure=True,
            password=password,
            verbose=verbose
        )
        
        # 3. Check results
        if result['success']:
            if verbose:
                print(f"[Archive] Successfully extracted {len(result['extracted_files'])} file(s)")
            return temp_dir, result
        
        # 4. Handle Password Errors during extraction
        if result.get('is_password_error'):
            if attempt < max_attempts - 1:
                if verbose:
                    print(f"[Archive] Wrong password or archive is encrypted.")
                password = _prompt_for_password(attempt > 0)
                if password is None: break
                continue # Retry with new password
            else:
                if verbose:
                    print("[Archive] Maximum password attempts reached.")
                break
        else:
            # Failed for a non-password reason (e.g. corrupted, out of space)
            break
            
    # If we get here, all attempts failed
    errors = result.get('errors', ['Unknown error'])
    shutil.rmtree(temp_dir, ignore_errors=True)
    return None, {'success': False, 'errors': errors}


def _prompt_for_password(is_retry: bool = False) -> Optional[str]:
    """Prompt user for password securely. Returns None if user cancels."""
    try:
        prompt_msg = "[Archive] Enter archive password: " if not is_retry else "[Archive] Wrong password. Try again (or press Ctrl+C to cancel): "
        pwd = getpass.getpass(prompt=prompt_msg)
        return pwd if pwd else ""
    except (EOFError, KeyboardInterrupt):
        print("\n[Archive] Cancelled by user.")
        return None


def cleanup_temp_dir(temp_dir: Union[str, Path], verbose: bool = True):
    """Clean up temporary directory."""
    if temp_dir and Path(temp_dir).exists():
        try:
            shutil.rmtree(temp_dir)
            if verbose:
                print(f"[Archive] Cleaned up temporary files")
        except Exception as e:
            if verbose:
                print(f"[Archive] Warning: Could not clean up temp files: {e}")