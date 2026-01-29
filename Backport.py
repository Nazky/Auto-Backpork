"""
PS5 Backport Library
A library for processing PS5 ELF/SELF files including SDK downgrade, fake signing, and decryption.
"""

import os
import sys
import shutil
import argparse
import subprocess
import tempfile
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union, Any
try:
    from src.ps5_sdk_version_patcher import SDKVersionPatcher
    from src.make_fself import FakeSignedELFConverter
    from src.decrypt_fself import UnsignedELFConverter
except ImportError:
    try:
        from .src.ps5_sdk_version_patcher import SDKVersionPatcher
        from .src.make_fself import FakeSignedELFConverter
        from .src.decrypt_fself import UnsignedELFConverter
    except ImportError:
        raise ImportError(
            "Could not import required modules. "
            "Please ensure ps5_sdk_version_patcher.py, make_fself.py, "
            "and decrypt_fself.py are available in the src folder."
        )

# ANSI color codes
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
CYAN = '\033[96m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

# Configuration file path
CONFIG_FILE = "ps5_backport_config.json"


class PS5ELFProcessor:
    """Main class for PS5 ELF processing operations."""
    
    # Constants for libc.prx patching
    LIBC_PATCH_PATTERN = b'4h6F1LLbTiw#A#B'
    LIBC_PATCH_REPLACEMENT = b'IWIBBdTHit4#A#B'
    
    def __init__(self, use_colors: bool = True, project_root: Optional[Union[str, Path]] = None):
        """
        Initialize the PS5 ELF processor.
        
        Args:
            use_colors: Whether to use colored output in console
            project_root: Root directory of the project (for finding fakelib). 
                         If None, uses directory of this file.
        """
        self.use_colors = use_colors
        self.project_root = Path(project_root) if project_root else Path(__file__).parent
    
    def _color(self, text: str, color_code: str) -> str:
        """Apply color to text if colors are enabled."""
        return color_code + text + RESET if self.use_colors else text
    
    def _print(self, message: str, color: Optional[str] = None, bold: bool = False):
        """Print a message with optional color and bold."""
        if color:
            message = self._color(message, color)
        if bold and self.use_colors:
            message = BOLD + message
        print(message)
    
    def _is_elf_file(self, file_path: Path) -> bool:
        """Check if a file is an ELF file by checking its magic bytes."""
        if file_path.name.endswith('.bak'):
            return False
        
        try:
            with open(file_path, 'rb') as f:
                magic = f.read(4)
                return magic == b'\x7FELF'
        except:
            return False
    
    def _is_self_file(self, file_path: Path) -> bool:
        """Check if a file is a SELF file by checking its magic bytes."""
        if file_path.name.endswith('.bak'):
            return False
        
        try:
            with open(file_path, 'rb') as f:
                magic = f.read(4)
                return magic in [b'\x4F\x15\x3D\x1D', b'\x54\x14\xF5\xEE']
        except:
            return False
    
    def _should_skip_dir(self, dirs: List[str], skip_name: str = 'decrypted') -> None:
        """Remove directories with specific names (case-insensitive) from the dirs list to skip them."""
        dirs_to_remove = [d for d in dirs if d.lower() == skip_name.lower()]
        for dir_name in dirs_to_remove:
            dirs.remove(dir_name)
    
    def get_supported_sdk_pairs(self) -> Dict[int, Tuple[int, int]]:
        """Get all supported SDK version pairs."""
        return SDKVersionPatcher.get_supported_pairs()
    
    def get_sdk_pair_info(self, sdk_pair: int) -> Optional[Tuple[int, int]]:
        """Get PS5 and PS4 SDK versions for a specific pair."""
        pairs = self.get_supported_sdk_pairs()
        return pairs.get(sdk_pair)
    
    def parse_ptype(self, ptype_str: str) -> int:
        """Parse program type from string (e.g., 'fake', 'npdrm_exec')."""
        return FakeSignedELFConverter.parse_ptype(ptype_str.lower())
    
    def decrypt_files(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        overwrite: bool = False,
        verbose: bool = True,
        save_to_config: bool = True
    ) -> Dict[str, Any]:
        """
        Decrypt SELF files back to ELF files.
        
        Args:
            input_dir: Directory containing SELF files
            output_dir: Directory for output ELF files
            overwrite: Overwrite existing files
            verbose: Print progress information
            save_to_config: Whether to save directories to config file (default: True)
            
        Returns:
            Dictionary with processing results
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)
        
        # Save directories to config only if requested
        if save_to_config:
            self._save_directories_to_config(str(input_dir), str(output_dir))
        
        results = {
            'operation': 'decrypt',
            'input_dir': str(input_dir),
            'output_dir': str(output_dir),
            'successful': 0,
            'failed': 0,
            'files': {},
            'timestamp': self._get_timestamp()
        }
        
        if verbose:
            self._print(f"\n[Step 1/1] Decrypting SELF Files", BLUE, bold=True)
            self._print(f"Input: {input_dir}", CYAN)
            self._print(f"Output: {output_dir}", CYAN)
        
        # Find all SELF files in input directory
        self_files = []
        for root, dirs, files in os.walk(input_dir):
            # Skip folders named "decrypted"
            self._should_skip_dir(dirs, 'decrypted')
            
            for filename in files:
                file_path = Path(root) / filename
                if filename.endswith('.bak'):
                    continue
                if self._is_self_file(file_path):
                    self_files.append(file_path)
        
        if not self_files:
            if verbose:
                self._print(f"No SELF files found in input directory", YELLOW)
            return results
        
        if verbose:
            self._print(f"Found {len(self_files)} SELF file(s) to decrypt", CYAN)
        
        # Create output directory structure
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize converter
        converter = UnsignedELFConverter(verbose=verbose)
        
        for self_file in self_files:
            relative_path = self_file.relative_to(input_dir)
            
            # Output file keeps same name and extension
            output_file = output_dir / relative_path
            
            # Create parent directories if they don't exist
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Check if file exists and skip if not overwriting
            if output_file.exists() and not overwrite:
                if verbose:
                    self._print(f"Skipping (exists): {relative_path}", YELLOW)
                continue
            
            if verbose:
                self._print(f"Decrypting: {relative_path}", None)
            
            # Decrypt the file
            try:
                success = converter.convert_file(str(self_file), str(output_file))
                
                file_result = {
                    'success': success,
                    'output': str(output_file),
                    'message': 'Success' if success else 'Failed'
                }
                
                results['files'][str(self_file)] = file_result
                
                if success:
                    results['successful'] += 1
                    if verbose:
                        self._print(f"  ✓ Success", GREEN)
                else:
                    results['failed'] += 1
                    if verbose:
                        self._print(f"  ✗ Failed", RED)
                        
            except Exception as e:
                results['failed'] += 1
                error_msg = f"Error: {str(e)}"
                file_result = {
                    'success': False,
                    'output': str(output_file),
                    'message': error_msg
                }
                results['files'][str(self_file)] = file_result
                if verbose:
                    self._print(f"  ✗ {error_msg[:50]}", RED)
        
        if verbose:
            self._print(f"\nDecryption complete: {results['successful']} successful, "
                       f"{results['failed']} failed", CYAN)
        
        return results
    
    def apply_libc_patch(
        self,
        input_dir: Union[str, Path],
        search_pattern: bytes = None,
        replacement_pattern: bytes = None,
        create_backup: bool = True,
        verbose: bool = True
    ) -> Dict[str, Any]:
        """
        Apply the libc.prx patch to SELF files in the directory or a single file.
        
        Args:
            input_dir: Directory containing SELF files to patch OR a single file path
            search_pattern: Bytes pattern to search for (defaults to LIBC_PATCH_PATTERN)
            replacement_pattern: Bytes pattern to replace with (defaults to LIBC_PATCH_REPLACEMENT)
            create_backup: Create backup files before patching
            verbose: Print progress information
            
        Returns:
            Dictionary with patching results
        """
        input_path = Path(input_dir)
        
        if search_pattern is None:
            search_pattern = self.LIBC_PATCH_PATTERN
        if replacement_pattern is None:
            replacement_pattern = self.LIBC_PATCH_REPLACEMENT
        
        results = {
            'operation': 'apply_libc_patch',
            'input_path': str(input_path),
            'is_file': input_path.is_file(),
            'search_pattern': search_pattern.hex(),
            'replacement_pattern': replacement_pattern.hex(),
            'applied': 0,
            'already_patched': 0,
            'pattern_not_found': 0,
            'failed': 0,
            'files': {},
            'timestamp': self._get_timestamp()
        }
        
        if verbose:
            self._print(f"\n[Libc Patch] Applying libc.prx patch", BLUE, bold=True)
            if input_path.is_file():
                self._print(f"Input file: {input_path}", CYAN)
            else:
                self._print(f"Input directory: {input_path}", CYAN)
            self._print(f"Search pattern: {search_pattern}", CYAN)
            self._print(f"Replacement pattern: {replacement_pattern}", CYAN)
        
        # Collect files to patch
        files_to_patch = []
        
        if input_path.is_file():
            # Single file input
            if self._is_self_file(input_path) or 'libc' in input_path.name.lower():
                files_to_patch.append(input_path)
            elif verbose:
                self._print(f"Warning: Input file may not be a SELF or libc file", YELLOW)
                files_to_patch.append(input_path)  # Try anyway
        else:
            # Directory input - search recursively
            for root, dirs, files in os.walk(input_path):
                # Skip folders named "decrypted"
                self._should_skip_dir(dirs, 'decrypted')
                
                for filename in files:
                    file_path = Path(root) / filename
                    if filename.endswith('.bak'):
                        continue
                    if self._is_self_file(file_path):
                        files_to_patch.append(file_path)
            
            # Also search for libc.prx files specifically
            for root, dirs, files in os.walk(input_path):
                # Skip folders named "decrypted"
                self._should_skip_dir(dirs, 'decrypted')
                
                for filename in files:
                    file_path = Path(root) / filename
                    if filename.lower() == 'libc.prx' and file_path not in files_to_patch:
                        files_to_patch.append(file_path)
        
        if not files_to_patch:
            if verbose:
                if input_path.is_file():
                    self._print(f"Input file is not a recognized SELF or libc file", YELLOW)
                else:
                    self._print(f"No SELF files found in input directory", YELLOW)
            return results
        
        if verbose:
            if input_path.is_file():
                self._print(f"Checking 1 file", CYAN)
            else:
                self._print(f"Found {len(files_to_patch)} file(s) to check for libc patch", CYAN)
        
        for file_path in files_to_patch:
            # For single file input, show just filename. For directory input, show relative path
            if input_path.is_file():
                display_path = file_path.name
            else:
                relative_path = file_path.relative_to(input_path)
                display_path = str(relative_path)
            
            if verbose:
                self._print(f"Checking: {display_path}", None)
            
            try:
                # Read file content
                with open(file_path, 'rb') as f:
                    content = f.read()
                
                # Check if pattern exists
                if search_pattern in content:
                    # Check if already has replacement pattern
                    if replacement_pattern in content:
                        results['already_patched'] += 1
                        results['files'][str(file_path)] = {
                            'status': 'already_patched',
                            'message': 'File already contains replacement pattern'
                        }
                        if verbose:
                            self._print(f"  ⚠ Already patched", YELLOW)
                        continue
                    
                    # Create backup if requested
                    backup_path = None
                    if create_backup:
                        backup_path = file_path.with_suffix('.bak')
                        shutil.copy2(file_path, backup_path)
                    
                    try:
                        # Apply patch
                        patched_content = content.replace(search_pattern, replacement_pattern)
                        
                        # Write patched content
                        with open(file_path, 'wb') as f:
                            f.write(patched_content)
                        
                        # Verify patch
                        with open(file_path, 'rb') as f:
                            new_content = f.read()
                        
                        if search_pattern not in new_content and replacement_pattern in new_content:
                            results['applied'] += 1
                            file_result = {
                                'status': 'applied',
                                'backup': str(backup_path) if backup_path else None,
                                'message': 'Patch applied successfully'
                            }
                            results['files'][str(file_path)] = file_result
                            
                            if verbose:
                                self._print(f"  ✓ Patch applied", GREEN)
                        else:
                            # Restore from backup if exists
                            if backup_path and backup_path.exists():
                                shutil.copy2(backup_path, file_path)
                            
                            results['failed'] += 1
                            file_result = {
                                'status': 'failed',
                                'message': 'Patch verification failed'
                            }
                            results['files'][str(file_path)] = file_result
                            
                            if verbose:
                                self._print(f"  ✗ Patch verification failed", RED)
                        
                        # Clean up backup if successful
                        if backup_path and backup_path.exists():
                            try:
                                os.remove(backup_path)
                                if 'backup' in file_result:
                                    file_result['backup_cleaned'] = True
                            except:
                                pass
                        
                    except Exception as e:
                        # Restore from backup on error
                        if backup_path and backup_path.exists():
                            shutil.copy2(backup_path, file_path)
                        
                        results['failed'] += 1
                        file_result = {
                            'status': 'error',
                            'message': f"Error during patching: {str(e)}"
                        }
                        results['files'][str(file_path)] = file_result
                        
                        if verbose:
                            self._print(f"  ✗ Error: {str(e)[:50]}", RED)
                
                else:
                    # Pattern not found in this file
                    results['pattern_not_found'] += 1
                    results['files'][str(file_path)] = {
                        'status': 'pattern_not_found',
                        'message': 'Search pattern not found in file'
                    }
                    
                    if 'libc' in file_path.name.lower():
                        if verbose:
                            self._print(f"  ⚠ Pattern not found in libc file", YELLOW)
                    elif verbose:
                        self._print(f"  Pattern not found", CYAN)
                    
            except Exception as e:
                results['failed'] += 1
                file_result = {
                    'status': 'error',
                    'message': f"Error reading file: {str(e)}"
                }
                results['files'][str(file_path)] = file_result
                
                if verbose:
                    self._print(f"  ✗ Error reading file: {str(e)[:50]}", RED)
        
        if verbose:
            self._print(f"\nLibc patch complete:", CYAN)
            self._print(f"  Applied: {results['applied']}", GREEN)
            self._print(f"  Already patched: {results['already_patched']}", YELLOW)
            self._print(f"  Pattern not found: {results['pattern_not_found']}")
            self._print(f"  Failed: {results['failed']}", RED if results['failed'] > 0 else "")
        
        return results
    
    def revert_libc_patch(
        self,
        input_dir: Union[str, Path],
        search_pattern: bytes = None,
        original_pattern: bytes = None,
        create_backup: bool = True,
        verbose: bool = True
    ) -> Dict[str, Any]:
        """
        Revert the libc.prx patch from SELF files in the directory or a single file.
        This restores files patched by apply_libc_patch() back to their original state.
        
        Args:
            input_dir: Directory containing SELF files to revert OR a single file path
            search_pattern: Bytes pattern to search for (defaults to LIBC_PATCH_REPLACEMENT)
            original_pattern: Bytes pattern to restore (defaults to LIBC_PATCH_PATTERN)
            create_backup: Create backup files before reverting
            verbose: Print progress information
            
        Returns:
            Dictionary with reversion results
        """
        input_path = Path(input_dir)
        
        if search_pattern is None:
            search_pattern = self.LIBC_PATCH_REPLACEMENT
        if original_pattern is None:
            original_pattern = self.LIBC_PATCH_PATTERN
        
        results = {
            'operation': 'revert_libc_patch',
            'input_path': str(input_path),
            'is_file': input_path.is_file(),
            'search_pattern': search_pattern.hex(),
            'original_pattern': original_pattern.hex(),
            'reverted': 0,
            'already_original': 0,
            'patch_not_found': 0,
            'failed': 0,
            'files': {},
            'timestamp': self._get_timestamp()
        }
        
        if verbose:
            self._print(f"\n[Libc Patch] Reverting libc.prx patch", BLUE, bold=True)
            if input_path.is_file():
                self._print(f"Input file: {input_path}", CYAN)
            else:
                self._print(f"Input directory: {input_path}", CYAN)
            self._print(f"Search pattern: {search_pattern}", CYAN)
            self._print(f"Restore pattern: {original_pattern}", CYAN)
            self._print(f"This will restore files to original state for SDK > 6", CYAN)
        
        # Collect files to revert
        files_to_revert = []
        
        if input_path.is_file():
            # Single file input
            if self._is_self_file(input_path) or 'libc' in input_path.name.lower():
                files_to_revert.append(input_path)
            elif verbose:
                self._print(f"Warning: Input file may not be a SELF or libc file", YELLOW)
                files_to_revert.append(input_path)  # Try anyway
        else:
            # Directory input - search recursively
            for root, dirs, files in os.walk(input_path):
                # Skip folders named "decrypted"
                self._should_skip_dir(dirs, 'decrypted')
                
                for filename in files:
                    file_path = Path(root) / filename
                    if filename.endswith('.bak'):
                        continue
                    if self._is_self_file(file_path):
                        files_to_revert.append(file_path)
            
            # Also search for libc.prx files specifically
            for root, dirs, files in os.walk(input_path):
                # Skip folders named "decrypted"
                self._should_skip_dir(dirs, 'decrypted')
                
                for filename in files:
                    file_path = Path(root) / filename
                    if filename.lower() == 'libc.prx' and file_path not in files_to_revert:
                        files_to_revert.append(file_path)
        
        if not files_to_revert:
            if verbose:
                if input_path.is_file():
                    self._print(f"Input file is not a recognized SELF or libc file", YELLOW)
                else:
                    self._print(f"No SELF files found in input directory", YELLOW)
            return results
        
        if verbose:
            if input_path.is_file():
                self._print(f"Checking 1 file", CYAN)
            else:
                self._print(f"Found {len(files_to_revert)} file(s) to check for libc patch reversion", CYAN)
        
        for file_path in files_to_revert:
            # For single file input, show just filename. For directory input, show relative path
            if input_path.is_file():
                display_path = file_path.name
            else:
                relative_path = file_path.relative_to(input_path)
                display_path = str(relative_path)
            
            if verbose:
                self._print(f"Checking: {display_path}", None)
            
            try:
                # Read file content
                with open(file_path, 'rb') as f:
                    content = f.read()
                
                # Check if patch pattern exists
                if search_pattern in content:
                    # Check if already has original pattern (already reverted)
                    if original_pattern in content:
                        results['already_original'] += 1
                        results['files'][str(file_path)] = {
                            'status': 'already_original',
                            'message': 'File already contains original pattern'
                        }
                        if verbose:
                            self._print(f"  ⚠ Already original", YELLOW)
                        continue
                    
                    # Create backup if requested
                    backup_path = None
                    if create_backup:
                        backup_path = file_path.with_suffix('.revert_bak')
                        shutil.copy2(file_path, backup_path)
                    
                    try:
                        # Revert patch
                        reverted_content = content.replace(search_pattern, original_pattern)
                        
                        # Write reverted content
                        with open(file_path, 'wb') as f:
                            f.write(reverted_content)
                        
                        # Verify reversion
                        with open(file_path, 'rb') as f:
                            new_content = f.read()
                        
                        if original_pattern in new_content and search_pattern not in new_content:
                            results['reverted'] += 1
                            file_result = {
                                'status': 'reverted',
                                'backup': str(backup_path) if backup_path else None,
                                'message': 'Patch reverted successfully'
                            }
                            results['files'][str(file_path)] = file_result
                            
                            if verbose:
                                self._print(f"  ✓ Patch reverted", GREEN)
                        else:
                            # Restore from backup if exists
                            if backup_path and backup_path.exists():
                                shutil.copy2(backup_path, file_path)
                            
                            results['failed'] += 1
                            file_result = {
                                'status': 'failed',
                                'message': 'Reversion verification failed'
                            }
                            results['files'][str(file_path)] = file_result
                            
                            if verbose:
                                self._print(f"  ✗ Reversion verification failed", RED)
                        
                        # Clean up backup if successful
                        if backup_path and backup_path.exists():
                            try:
                                os.remove(backup_path)
                                if 'backup' in file_result:
                                    file_result['backup_cleaned'] = True
                            except:
                                pass
                        
                    except Exception as e:
                        # Restore from backup on error
                        if backup_path and backup_path.exists():
                            shutil.copy2(backup_path, file_path)
                        
                        results['failed'] += 1
                        file_result = {
                            'status': 'error',
                            'message': f"Error during reversion: {str(e)}"
                        }
                        results['files'][str(file_path)] = file_result
                        
                        if verbose:
                            self._print(f"  ✗ Error: {str(e)[:50]}", RED)
                
                else:
                    # Patch pattern not found in this file
                    results['patch_not_found'] += 1
                    results['files'][str(file_path)] = {
                        'status': 'patch_not_found',
                        'message': 'Patch pattern not found in file'
                    }
                    
                    if verbose and 'libc' in file_path.name.lower():
                        self._print(f"  ⚠ Patch pattern not found in libc file", YELLOW)
                    elif verbose:
                        self._print(f"  Patch pattern not found", CYAN)
                    
            except Exception as e:
                results['failed'] += 1
                file_result = {
                    'status': 'error',
                    'message': f"Error reading file: {str(e)}"
                }
                results['files'][str(file_path)] = file_result
                
                if verbose:
                    self._print(f"  ✗ Error reading file: {str(e)[:50]}", RED)
        
        if verbose:
            self._print(f"\nLibc patch reversion complete:", CYAN)
            self._print(f"  Reverted: {results['reverted']}", GREEN)
            self._print(f"  Already original: {results['already_original']}", YELLOW)
            self._print(f"  Patch not found: {results['patch_not_found']}")
            self._print(f"  Failed: {results['failed']}", RED if results['failed'] > 0 else "")
        
        return results
    
    def check_libc_patch_status(
        self,
        input_path: Union[str, Path],
        search_pattern: bytes = None,
        patch_pattern: bytes = None,
        verbose: bool = True
    ) -> Dict[str, Any]:
        """
        Check the status of libc.prx patches in SELF files or a single file.
        
        Args:
            input_path: Directory containing SELF files OR a single file to check
            search_pattern: Original bytes pattern (defaults to LIBC_PATCH_PATTERN)
            patch_pattern: Patch bytes pattern (defaults to LIBC_PATCH_REPLACEMENT)
            verbose: Print progress information
            
        Returns:
            Dictionary with patch status information
        """
        input_path = Path(input_path)
        
        if search_pattern is None:
            search_pattern = self.LIBC_PATCH_PATTERN
        if patch_pattern is None:
            patch_pattern = self.LIBC_PATCH_REPLACEMENT
        
        results = {
            'operation': 'check_libc_patch_status',
            'input_path': str(input_path),
            'is_file_input': input_path.is_file(),
            'original_pattern': search_pattern.hex(),
            'patch_pattern': patch_pattern.hex(),
            'original_files': [],
            'patched_files': [],
            'both_patterns_files': [],
            'no_pattern_files': [],
            'error_files': [],
            'total_files': 0,
            'timestamp': self._get_timestamp()
        }
        
        if verbose:
            self._print(f"\n[Libc Patch] Checking libc.prx patch status", BLUE, bold=True)
            if input_path.is_file():
                self._print(f"Input: Single file: {input_path}", CYAN)
            else:
                self._print(f"Input: Directory: {input_path}", CYAN)
        
        # Collect files to check
        self_files = []
        
        if input_path.is_file():
            # Single file input
            if self._is_self_file(input_path) or 'libc' in input_path.name.lower():
                self_files.append(input_path)
            elif verbose:
                self._print(f"Input file may not be a recognized SELF or libc file", YELLOW)
                self_files.append(input_path)  # Try to check anyway
        else:
            # Directory input - search recursively
            for root, dirs, files in os.walk(input_path):
                # Skip folders named "decrypted"
                self._should_skip_dir(dirs, 'decrypted')
                
                for filename in files:
                    file_path = Path(root) / filename
                    if filename.endswith('.bak'):
                        continue
                    if self._is_self_file(file_path):
                        self_files.append(file_path)
            
            # Also search for libc.prx files specifically
            for root, dirs, files in os.walk(input_path):
                # Skip folders named "decrypted"
                self._should_skip_dir(dirs, 'decrypted')
                
                for filename in files:
                    file_path = Path(root) / filename
                    if filename.lower() == 'libc.prx' and file_path not in self_files:
                        self_files.append(file_path)
        
        if not self_files:
            if verbose:
                if input_path.is_file():
                    self._print(f"Input file is not a valid SELF or libc file", YELLOW)
                else:
                    self._print(f"No SELF files found in input directory", YELLOW)
            return results
        
        results['total_files'] = len(self_files)
        
        if verbose:
            if input_path.is_file():
                self._print(f"Checking 1 file", CYAN)
            else:
                self._print(f"Found {len(self_files)} file(s) to check", CYAN)
        
        for file_path in self_files:
            # For single file input, show just filename. For directory input, show relative path
            if input_path.is_file():
                display_path = file_path.name
                relative_path = file_path  # Use full path for single file
            else:
                relative_path = file_path.relative_to(input_path)
                display_path = str(relative_path)
            
            try:
                # Read file content
                with open(file_path, 'rb') as f:
                    content = f.read()
                
                has_original = search_pattern in content
                has_patch = patch_pattern in content
                
                file_info = {
                    'path': str(file_path),
                    'has_original': has_original,
                    'has_patch': has_patch,
                    'is_libc_file': 'libc' in file_path.name.lower()
                }
                
                # Add relative path only for directory inputs
                if not input_path.is_file():
                    file_info['relative_path'] = str(relative_path)
                
                if has_original and not has_patch:
                    results['original_files'].append(file_info)
                    status = "Original (not patched)"
                    color = GREEN
                elif has_patch and not has_original:
                    results['patched_files'].append(file_info)
                    status = "Patched"
                    color = YELLOW
                elif has_original and has_patch:
                    results['both_patterns_files'].append(file_info)
                    status = "Both patterns found (error)"
                    color = RED
                else:
                    results['no_pattern_files'].append(file_info)
                    status = "No patterns found"
                    color = CYAN
                
                if verbose:
                    status_display = f"{display_path}"
                    if 'libc' in file_path.name.lower():
                        status_display += " [libc]"
                    self._print(f"{status_display}: {status}", color)
                
            except Exception as e:
                error_info = {
                    'path': str(file_path),
                    'error': str(e)
                }
                # Add relative path only for directory inputs
                if not input_path.is_file():
                    error_info['relative_path'] = str(relative_path)
                
                results['error_files'].append(error_info)
                
                if verbose:
                    self._print(f"{display_path}: Error reading file", RED)
        
        if verbose:
            self._print(f"\nPatch status summary:", BLUE, bold=True)
            self._print(f"  Original files (not patched): {len(results['original_files'])}", GREEN)
            self._print(f"  Patched files: {len(results['patched_files'])}", YELLOW)
            self._print(f"  Both patterns (error): {len(results['both_patterns_files'])}", RED)
            self._print(f"  No patterns: {len(results['no_pattern_files'])}", CYAN)
            self._print(f"  Error reading: {len(results['error_files'])}", RED)
            self._print(f"  Total files: {results['total_files']}")
        
        return results
    
    def check_libc_patch_in_file(
        self,
        input_file: Union[str, Path],
        search_pattern: bytes = None,
        patch_pattern: bytes = None,
        verbose: bool = True
    ) -> Dict[str, Any]:
        """
        Check the status of libc.prx patch in a single file.
        
        Args:
            input_file: Single file to check
            search_pattern: Original bytes pattern (defaults to LIBC_PATCH_PATTERN)
            patch_pattern: Patch bytes pattern (defaults to LIBC_PATCH_REPLACEMENT)
            verbose: Print progress information
            
        Returns:
            Dictionary with patch status information
        """
        input_path = Path(input_file)
        
        if not input_path.exists():
            return {
                'operation': 'check_libc_patch_in_file',
                'input_file': str(input_file),
                'error': 'File does not exist',
                'timestamp': self._get_timestamp()
            }
        
        if not input_path.is_file():
            return {
                'operation': 'check_libc_patch_in_file',
                'input_file': str(input_file),
                'error': 'Path is not a file',
                'timestamp': self._get_timestamp()
            }
        
        # Use the existing method but for single file
        return self.check_libc_patch_status(
            input_path=input_file,
            search_pattern=search_pattern,
            patch_pattern=patch_pattern,
            verbose=verbose
        )
    
    def downgrade_and_sign(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        sdk_pair: int,
        paid: int,
        ptype: int,
        fakelib_source: Optional[Union[str, Path]] = None,
        create_backup: bool = True,
        overwrite: bool = False,
        apply_libc_patch: bool = True,
        auto_revert_for_high_sdk: bool = True,
        verbose: bool = True,
        save_to_config: bool = True
    ) -> Dict[str, Any]:
        """
        Process files through downgrade and signing pipeline.
        IMPORTANT: libc.prx patch is applied AFTER signing to the SELF files.
        
        Args:
            input_dir: Directory containing ELF files
            output_dir: Directory for output SELF files
            sdk_pair: SDK version pair number (1-10)
            paid: Program Authentication ID
            ptype: Program type
            fakelib_source: Optional custom fakelib directory
            create_backup: Whether to create backups during downgrade
            overwrite: Overwrite existing files
            apply_libc_patch: Apply libc.prx patch for SDK pairs 1-6
            auto_revert_for_high_sdk: Automatically revert patch if SDK > 6
            verbose: Print progress information
            save_to_config: Whether to save directories to config file (default: True)
            
        Returns:
            Dictionary with processing results
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)
        
        # Save directories to config only if requested
        if save_to_config:
            self._save_directories_to_config(str(input_dir), str(output_dir))
        
        results = {
            'operation': 'downgrade_and_sign',
            'input_dir': str(input_dir),
            'output_dir': str(output_dir),
            'sdk_pair': sdk_pair,
            'paid': paid,
            'ptype': ptype,
            'downgrade': {'successful': 0, 'failed': 0, 'files': {}},
            'signing': {'successful': 0, 'failed': 0, 'files': {}},
            'fakelib': {'success': False, 'message': ''},
            'libc_patch': {'applied': 0, 'reverted': 0, 'results': {}},
            'fakelib_copies': {'created': 0, 'locations': []},
            'timestamp': self._get_timestamp()
        }
        
        if verbose:
            self._print(f"\n[Step 1/4] Downgrading SDK Versions", BLUE, bold=True)
            self._print(f"Input: {input_dir}", CYAN)
            self._print(f"Output: {output_dir}", CYAN)
        
        # Step 1: Downgrade SDK versions on ELF files
        sdk_patcher = SDKVersionPatcher(
            create_backup=create_backup,
            use_colors=self.use_colors
        )
        sdk_patcher.set_versions_by_pair(sdk_pair)
        
        ps5_ver, ps4_ver = sdk_patcher.get_current_versions()
        results['ps5_sdk_version'] = ps5_ver
        results['ps4_sdk_version'] = ps4_ver
        
        if verbose:
            self._print(f"Using PS5 SDK: 0x{ps5_ver:08X}, PS4 Version: 0x{ps4_ver:08X}", CYAN)
            if sdk_pair <= 6:
                self._print(f"SDK pair {sdk_pair} selected - will apply libc.prx patch AFTER signing", YELLOW)
            elif auto_revert_for_high_sdk:
                self._print(f"SDK pair {sdk_pair} > 6 - will revert libc.prx patch AFTER signing if found", YELLOW)
        
        # Find all ELF files in input directory
        elf_files = []
        for root, dirs, files in os.walk(input_dir):
            # Skip folders named "decrypted"
            self._should_skip_dir(dirs, 'decrypted')
            
            for filename in files:
                file_path = Path(root) / filename
                if filename.endswith('.bak'):
                    continue
                if self._is_elf_file(file_path):
                    elf_files.append(file_path)
        
        if not elf_files:
            if verbose:
                self._print(f"No ELF files found in input directory", YELLOW)
            return results
        
        if verbose:
            self._print(f"Found {len(elf_files)} ELF file(s) to process", CYAN)
        
        for elf_file in elf_files:
            relative_path = elf_file.relative_to(input_dir)
            
            if verbose:
                self._print(f"Downgrading: {relative_path}", None)
            
            try:
                success, message = sdk_patcher.patch_file(str(elf_file))
                
                results['downgrade']['files'][str(elf_file)] = {
                    'success': success,
                    'message': message
                }
                
                if success:
                    results['downgrade']['successful'] += 1
                    if verbose:
                        self._print(f"  ✓ Success", GREEN)
                else:
                    results['downgrade']['failed'] += 1
                    if verbose:
                        self._print(f"  ✗ {message[:50]}", RED)
                        
            except Exception as e:
                results['downgrade']['failed'] += 1
                error_msg = f"Error: {str(e)}"
                results['downgrade']['files'][str(elf_file)] = {
                    'success': False,
                    'message': error_msg
                }
                if verbose:
                    self._print(f"  ✗ {error_msg[:50]}", RED)
        
        if verbose:
            self._print(f"\nDowngrade complete: {results['downgrade']['successful']} successful, "
                       f"{results['downgrade']['failed']} failed", CYAN)
        
        # Step 2: Fake sign the downgraded ELF files to SELF format
        if verbose:
            self._print(f"\n[Step 2/4] Fake Signing Files (ELF → SELF)", BLUE, bold=True)
            self._print(f"Using PAID: 0x{paid:016X}, PType: 0x{ptype:08X}", CYAN)
        
        # Create output directory structure
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize converter
        converter = FakeSignedELFConverter(
            paid=paid,
            ptype=ptype,
            app_version=0,
            fw_version=0,
            auth_info=None
        )
        
        for elf_file in elf_files:
            relative_path = elf_file.relative_to(input_dir)
            input_file_str = str(elf_file)
            
            # Skip if downgrade failed
            if not results['downgrade']['files'].get(input_file_str, {}).get('success', False):
                if verbose:
                    self._print(f"Skipping (downgrade failed): {relative_path}", YELLOW)
                results['signing']['files'][str(elf_file)] = {
                    'success': False,
                    'output': '',
                    'message': 'Skipped due to downgrade failure'
                }
                results['signing']['failed'] += 1
                continue
            
            # Output file keeps same name but will be SELF format
            output_file = output_dir / relative_path
            
            # Create parent directories if they don't exist
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Check if file exists and skip if not overwriting
            if output_file.exists() and not overwrite:
                if verbose:
                    self._print(f"Skipping (exists): {relative_path}", YELLOW)
                continue
            
            if verbose:
                self._print(f"Signing: {relative_path}", None)
            
            # Sign the ELF file (converts to SELF format)
            try:
                success = converter.sign_file(input_file_str, str(output_file))
                
                results['signing']['files'][str(elf_file)] = {
                    'success': success,
                    'output': str(output_file),
                    'message': 'Success' if success else 'Failed'
                }
                
                if success:
                    results['signing']['successful'] += 1
                    if verbose:
                        self._print(f"  ✓ Success (converted to SELF)", GREEN)
                else:
                    results['signing']['failed'] += 1
                    if verbose:
                        self._print(f"  ✗ Failed", RED)
                        
            except Exception as e:
                results['signing']['failed'] += 1
                error_msg = f"Error: {str(e)}"
                results['signing']['files'][str(elf_file)] = {
                    'success': False,
                    'output': str(output_file),
                    'message': error_msg
                }
                if verbose:
                    self._print(f"  ✗ {error_msg[:50]}", RED)
        
        if verbose:
            self._print(f"\nSigning complete: {results['signing']['successful']} successful, "
                       f"{results['signing']['failed']} failed", CYAN)
            self._print(f"All ELF files have been converted to SELF format", CYAN)
        
        # Step 3: Handle libc.prx patch based on SDK version
        # IMPORTANT: This is done AFTER signing, on the SELF files
        if apply_libc_patch:
            if sdk_pair <= 6:
                # Apply patch for SDK 1-6 (on SELF files)
                if verbose:
                    self._print(f"\n[Step 3/4] Applying libc.prx patch to SELF files (SDK ≤ 6)", BLUE, bold=True)
                    self._print(f"Patching SELF files in output directory", CYAN)
                
                patch_results = self.apply_libc_patch(
                    output_dir,  # Patch the signed SELF files
                    create_backup=False,
                    verbose=verbose
                )
                results['libc_patch']['applied'] = patch_results['applied']
                results['libc_patch']['results'] = patch_results
                
            elif auto_revert_for_high_sdk:
                # Revert patch for SDK > 6 (on SELF files)
                if verbose:
                    self._print(f"\n[Step 3/4] Reverting libc.prx patch from SELF files (SDK > 6)", BLUE, bold=True)
                    self._print(f"Reverting patches in SELF files in output directory", CYAN)
                
                revert_results = self.revert_libc_patch(
                    output_dir,  # Revert patches on signed SELF files
                    create_backup=False,
                    verbose=verbose
                )
                results['libc_patch']['reverted'] = revert_results['reverted']
                results['libc_patch']['results'] = revert_results
        
        # Step 4: Copy fakelib directory to output directory AND to eboot.bin locations
        if fakelib_source:
            fakelib_source_path = Path(fakelib_source)
            if verbose:
                self._print(f"\n[Step 4/4] Copying Fakelib Directory", BLUE, bold=True)
            
            # First, copy to output directory (original behavior)
            success, message = self._copy_fakelib(fakelib_source_path, output_dir)
            results['fakelib']['success'] = success
            results['fakelib']['message'] = message
            
            if verbose:
                if success:
                    self._print(f"✓ {message}", GREEN)
                else:
                    self._print(f"⚠ {message}", YELLOW)
            
            # Also copy fakelib to directories containing eboot.bin files
            if success:
                fakelib_copies = self._copy_fakelib_to_eboot_dirs(fakelib_source_path, output_dir, verbose)
                results['fakelib_copies']['created'] = fakelib_copies['created']
                results['fakelib_copies']['locations'] = fakelib_copies['locations']
                
                if verbose and fakelib_copies['created'] > 0:
                    self._print(f"✓ Created {fakelib_copies['created']} fakelib copy(ies) in eboot.bin directories", GREEN)
        
        return results
    
    def decrypt_and_sign_pipeline(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        sdk_pair: int,
        paid: int,
        ptype: int,
        fakelib_source: Optional[Union[str, Path]] = None,
        create_backup: bool = True,
        overwrite: bool = False,
        apply_libc_patch: bool = True,
        auto_revert_for_high_sdk: bool = True,
        verbose: bool = True,
        save_to_config: bool = True
    ) -> Dict[str, Any]:
        """
        Process files through a combined pipeline that automatically detects file types.
        If files are SELF: decrypt → save to decrypted folder → downgrade → sign
        If files are ELF: downgrade → sign directly
        libc.prx patch is applied AFTER signing to the SELF files.
        
        Args:
            input_dir: Directory containing SELF or ELF files
            output_dir: Directory for final output SELF files
            sdk_pair: SDK version pair number (1-10)
            paid: Program Authentication ID
            ptype: Program type
            fakelib_source: Optional custom fakelib directory
            create_backup: Whether to create backups during downgrade
            overwrite: Overwrite existing files
            apply_libc_patch: Apply libc.prx patch for SDK pairs 1-6
            auto_revert_for_high_sdk: Automatically revert patch if SDK > 6
            verbose: Print progress information
            save_to_config: Whether to save directories to config file
            
        Returns:
            Dictionary with processing results
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)
        
        # Save directories to config only if requested
        if save_to_config:
            self._save_directories_to_config(str(input_dir), str(output_dir))
        
        results = {
            'operation': 'decrypt_and_sign_pipeline',
            'input_dir': str(input_dir),
            'output_dir': str(output_dir),
            'sdk_pair': sdk_pair,
            'paid': paid,
            'ptype': ptype,
            'detection': {'self_files': 0, 'elf_files': 0, 'other_files': 0},
            'decrypt': {'successful': 0, 'failed': 0, 'files': {}},
            'downgrade': {'successful': 0, 'failed': 0, 'files': {}},
            'signing': {'successful': 0, 'failed': 0, 'files': {}},
            'fakelib': {'success': False, 'message': ''},
            'libc_patch': {'applied': 0, 'reverted': 0, 'results': {}},
            'fakelib_copies': {'created': 0, 'locations': []},
            'decrypted_folder': None,
            'timestamp': self._get_timestamp()
        }
        
        if verbose:
            self._print(f"\n[Step 1/5] Detecting File Types", BLUE, bold=True)
            self._print(f"Input: {input_dir}", CYAN)
            self._print(f"Output: {output_dir}", CYAN)
        
        # Step 1: Detect file types
        self_files = []
        elf_files = []
        
        for root, dirs, files in os.walk(input_dir):
            # Skip folders named "decrypted"
            self._should_skip_dir(dirs, 'decrypted')
            
            for filename in files:
                file_path = Path(root) / filename
                if filename.endswith('.bak'):
                    continue
                
                if self._is_self_file(file_path):
                    self_files.append(file_path)
                    results['detection']['self_files'] += 1
                elif self._is_elf_file(file_path):
                    elf_files.append(file_path)
                    results['detection']['elf_files'] += 1
                else:
                    results['detection']['other_files'] += 1
        
        if verbose:
            self._print(f"Found: {len(self_files)} SELF file(s), {len(elf_files)} ELF file(s), "
                       f"{results['detection']['other_files']} other file(s)", CYAN)
        
        if not self_files and not elf_files:
            if verbose:
                self._print(f"No SELF or ELF files found in input directory", YELLOW)
            return results
        
        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Step 2: If there are SELF files, decrypt them first
        working_dir = output_dir / "working"
        decrypt_output_dir = output_dir / "decrypted"
        
        if self_files:
            if verbose:
                self._print(f"\n[Step 2/5] Decrypting SELF Files", BLUE, bold=True)
                self._print(f"Decrypting {len(self_files)} SELF file(s) to: {decrypt_output_dir}", CYAN)
            
            # Create decrypted output folder
            decrypt_output_dir.mkdir(parents=True, exist_ok=True)
            results['decrypted_folder'] = str(decrypt_output_dir)
            
            # Initialize converter
            converter = UnsignedELFConverter(verbose=verbose)
            
            for self_file in self_files:
                relative_path = self_file.relative_to(input_dir)
                
                # Output file in decrypted folder
                output_file = decrypt_output_dir / relative_path
                
                # Create parent directories if they don't exist
                output_file.parent.mkdir(parents=True, exist_ok=True)
                
                # Check if file exists and skip if not overwriting
                if output_file.exists() and not overwrite:
                    if verbose:
                        self._print(f"Skipping (exists): {relative_path}", YELLOW)
                    continue
                
                if verbose:
                    self._print(f"Decrypting: {relative_path}", None)
                
                # Decrypt the file
                try:
                    success = converter.convert_file(str(self_file), str(output_file))
                    
                    file_result = {
                        'success': success,
                        'output': str(output_file),
                        'message': 'Success' if success else 'Failed'
                    }
                    
                    results['decrypt']['files'][str(self_file)] = file_result
                    
                    if success:
                        results['decrypt']['successful'] += 1
                        if verbose:
                            self._print(f"  ✓ Success", GREEN)
                    else:
                        results['decrypt']['failed'] += 1
                        if verbose:
                            self._print(f"  ✗ Failed", RED)
                            
                except Exception as e:
                    results['decrypt']['failed'] += 1
                    error_msg = f"Error: {str(e)}"
                    file_result = {
                        'success': False,
                        'output': str(output_file),
                        'message': error_msg
                    }
                    results['decrypt']['files'][str(self_file)] = file_result
                    if verbose:
                        self._print(f"  ✗ {error_msg[:50]}", RED)
            
            if verbose:
                self._print(f"\nDecryption complete: {results['decrypt']['successful']} successful, "
                           f"{results['decrypt']['failed']} failed", CYAN)
            
            # Set working directory to decrypted files for downgrade/sign
            working_dir = decrypt_output_dir
            
        else:
            # No SELF files, use original ELF files directly
            working_dir = input_dir
        
        # Step 3: Copy any existing ELF files to working directory structure
        if elf_files and self_files:  # Only if we have both types
            if verbose:
                self._print(f"\n[Step 3/5] Copying existing ELF files to working directory", BLUE, bold=True)
            
            for elf_file in elf_files:
                relative_path = elf_file.relative_to(input_dir)
                dest_file = working_dir / relative_path
                
                # Create parent directories if they don't exist
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                
                if not dest_file.exists() or overwrite:
                    shutil.copy2(elf_file, dest_file)
                    if verbose:
                        self._print(f"Copied: {relative_path}", CYAN)
        
        # Step 4: Downgrade SDK versions
        if verbose:
            self._print(f"\n[Step 4/5] Downgrading SDK Versions", BLUE, bold=True)
            self._print(f"Processing files from: {working_dir}", CYAN)
        
        sdk_patcher = SDKVersionPatcher(
            create_backup=create_backup,
            use_colors=self.use_colors
        )
        sdk_patcher.set_versions_by_pair(sdk_pair)
        
        ps5_ver, ps4_ver = sdk_patcher.get_current_versions()
        results['ps5_sdk_version'] = ps5_ver
        results['ps4_sdk_version'] = ps4_ver
        
        if verbose:
            self._print(f"Using PS5 SDK: 0x{ps5_ver:08X}, PS4 Version: 0x{ps4_ver:08X}", CYAN)
            if sdk_pair <= 6:
                self._print(f"SDK pair {sdk_pair} selected - will apply libc.prx patch AFTER signing", YELLOW)
            elif auto_revert_for_high_sdk:
                self._print(f"SDK pair {sdk_pair} > 6 - will revert libc.prx patch AFTER signing if found", YELLOW)
        
        # Find all ELF files in working directory
        elf_files_to_process = []
        for root, dirs, files in os.walk(working_dir):
            # Skip folders named "decrypted" (including when working_dir is the decrypted folder)
            self._should_skip_dir(dirs, 'decrypted')
            
            for filename in files:
                file_path = Path(root) / filename
                if filename.endswith('.bak'):
                    continue
                if self._is_elf_file(file_path):
                    elf_files_to_process.append(file_path)
        
        if not elf_files_to_process:
            if verbose:
                self._print(f"No ELF files found to downgrade", YELLOW)
            return results
        
        if verbose:
            self._print(f"Found {len(elf_files_to_process)} ELF file(s) to downgrade", CYAN)
        
        for elf_file in elf_files_to_process:
            relative_path = elf_file.relative_to(working_dir)
            
            if verbose:
                self._print(f"Downgrading: {relative_path}", None)
            
            try:
                success, message = sdk_patcher.patch_file(str(elf_file))
                
                results['downgrade']['files'][str(elf_file)] = {
                    'success': success,
                    'message': message
                }
                
                if success:
                    results['downgrade']['successful'] += 1
                    if verbose:
                        self._print(f"  ✓ Success", GREEN)
                else:
                    results['downgrade']['failed'] += 1
                    if verbose:
                        self._print(f"  ✗ {message[:50]}", RED)
                    
            except Exception as e:
                results['downgrade']['failed'] += 1
                error_msg = f"Error: {str(e)}"
                results['downgrade']['files'][str(elf_file)] = {
                    'success': False,
                    'message': error_msg
                }
                if verbose:
                    self._print(f"  ✗ {error_msg[:50]}", RED)
        
        if verbose:
            self._print(f"\nDowngrade complete: {results['downgrade']['successful']} successful, "
                       f"{results['downgrade']['failed']} failed", CYAN)
        
        # Step 5: Fake sign the downgraded ELF files to SELF format
        if verbose:
            self._print(f"\n[Step 5/5] Fake Signing Files (ELF → SELF)", BLUE, bold=True)
            self._print(f"Using PAID: 0x{paid:016X}, PType: 0x{ptype:08X}", CYAN)
        
        # Initialize converter
        converter = FakeSignedELFConverter(
            paid=paid,
            ptype=ptype,
            app_version=0,
            fw_version=0,
            auth_info=None
        )
        
        for elf_file in elf_files_to_process:
            relative_path = elf_file.relative_to(working_dir)
            input_file_str = str(elf_file)
            
            # Skip if downgrade failed
            if not results['downgrade']['files'].get(input_file_str, {}).get('success', False):
                if verbose:
                    self._print(f"Skipping (downgrade failed): {relative_path}", YELLOW)
                results['signing']['files'][str(elf_file)] = {
                    'success': False,
                    'output': '',
                    'message': 'Skipped due to downgrade failure'
                }
                results['signing']['failed'] += 1
                continue
            
            # Output file keeps relative path structure
            output_file = output_dir / relative_path
            
            # Create parent directories if they don't exist
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Check if file exists and skip if not overwriting
            if output_file.exists() and not overwrite:
                if verbose:
                    self._print(f"Skipping (exists): {relative_path}", YELLOW)
                continue
            
            if verbose:
                self._print(f"Signing: {relative_path}", None)
            
            # Sign the ELF file (converts to SELF format)
            try:
                success = converter.sign_file(input_file_str, str(output_file))
                
                results['signing']['files'][str(elf_file)] = {
                    'success': success,
                    'output': str(output_file),
                    'message': 'Success' if success else 'Failed'
                }
                
                if success:
                    results['signing']['successful'] += 1
                    if verbose:
                        self._print(f"  ✓ Success (converted to SELF)", GREEN)
                else:
                    results['signing']['failed'] += 1
                    if verbose:
                        self._print(f"  ✗ Failed", RED)
                    
            except Exception as e:
                results['signing']['failed'] += 1
                error_msg = f"Error: {str(e)}"
                results['signing']['files'][str(elf_file)] = {
                    'success': False,
                    'output': str(output_file),
                    'message': error_msg
                }
                if verbose:
                    self._print(f"  ✗ {error_msg[:50]}", RED)
        
        if verbose:
            self._print(f"\nSigning complete: {results['signing']['successful']} successful, "
                       f"{results['signing']['failed']} failed", CYAN)
            self._print(f"All ELF files have been converted to SELF format", CYAN)
        
        # Step 6: Handle libc.prx patch based on SDK version
        # IMPORTANT: This is done AFTER signing, on the SELF files
        if apply_libc_patch:
            if sdk_pair <= 6:
                # Apply patch for SDK 1-6 (on SELF files)
                if verbose:
                    self._print(f"\n[Step 6/6] Applying libc.prx patch to SELF files (SDK ≤ 6)", BLUE, bold=True)
                    self._print(f"Patching SELF files in output directory", CYAN)
                
                patch_results = self.apply_libc_patch(
                    output_dir,  # Patch the signed SELF files
                    create_backup=False,
                    verbose=verbose
                )
                results['libc_patch']['applied'] = patch_results['applied']
                results['libc_patch']['results'] = patch_results
                
            elif auto_revert_for_high_sdk:
                # Revert patch for SDK > 6 (on SELF files)
                if verbose:
                    self._print(f"\n[Step 6/6] Reverting libc.prx patch from SELF files (SDK > 6)", BLUE, bold=True)
                    self._print(f"Reverting patches in SELF files in output directory", CYAN)
                
                revert_results = self.revert_libc_patch(
                    output_dir,  # Revert patches on signed SELF files
                    create_backup=False,
                    verbose=verbose
                )
                results['libc_patch']['reverted'] = revert_results['reverted']
                results['libc_patch']['results'] = revert_results
        
        # Step 7: Copy fakelib directory to output directory AND to eboot.bin locations
        if fakelib_source:
            fakelib_source_path = Path(fakelib_source)
            if verbose:
                self._print(f"\n[Step 7/7] Copying Fakelib Directory", BLUE, bold=True)
            
            # First, copy to output directory
            success, message = self._copy_fakelib(fakelib_source_path, output_dir)
            results['fakelib']['success'] = success
            results['fakelib']['message'] = message
            
            if verbose:
                if success:
                    self._print(f"✓ {message}", GREEN)
                else:
                    self._print(f"⚠ {message}", YELLOW)
            
            # Also copy fakelib to directories containing eboot.bin files
            if success:
                fakelib_copies = self._copy_fakelib_to_eboot_dirs(fakelib_source_path, output_dir, verbose)
                results['fakelib_copies']['created'] = fakelib_copies['created']
                results['fakelib_copies']['locations'] = fakelib_copies['locations']
                
                if verbose and fakelib_copies['created'] > 0:
                    self._print(f"✓ Created {fakelib_copies['created']} fakelib copy(ies) in eboot.bin directories", GREEN)
        
        return results
    
    def _copy_fakelib(self, fakelib_source: Path, output_dir: Path) -> Tuple[bool, str]:
        """Copy the fakelib directory to the output directory."""
        if not fakelib_source.exists():
            return True, f"fakelib directory not found at {fakelib_source} (skipping)"
        
        if not fakelib_source.is_dir():
            return False, f"fakelib path exists but is not a directory: {fakelib_source}"
        
        fakelib_dest = output_dir / "fakelib"
        
        try:
            # Remove existing fakelib in output if it exists
            if fakelib_dest.exists():
                shutil.rmtree(fakelib_dest)
            
            # Copy fakelib directory
            shutil.copytree(fakelib_source, fakelib_dest)
            
            # Count files for reporting
            file_count = sum(1 for _ in fakelib_dest.rglob('*') if _.is_file())
            return True, f"Copied fakelib directory from {fakelib_source} ({file_count} files)"
        
        except Exception as e:
            return False, f"Failed to copy fakelib: {str(e)}"
    
    def _copy_fakelib_to_eboot_dirs(self, fakelib_source: Path, output_dir: Path, verbose: bool = True) -> Dict[str, Any]:
        """Copy fakelib directory to directories containing eboot.bin files."""
        if not fakelib_source.exists() or not fakelib_source.is_dir():
            return {'created': 0, 'locations': []}
        
        results = {
            'created': 0,
            'locations': []
        }
        
        # Find all eboot.bin files in the output directory
        eboot_files = []
        for root, dirs, files in os.walk(output_dir):
            for filename in files:
                if filename.lower() == 'eboot.bin':
                    file_path = Path(root) / filename
                    eboot_files.append(file_path)
        
        if not eboot_files:
            if verbose:
                self._print(f"No eboot.bin files found in output directory", CYAN)
            return results
        
        if verbose:
            self._print(f"Found {len(eboot_files)} eboot.bin file(s)", CYAN)
        
        for eboot_file in eboot_files:
            eboot_dir = eboot_file.parent
            
            # Skip if this is already the main output directory
            if eboot_dir == output_dir:
                continue
            
            # Create fakelib directory in eboot directory
            fakelib_dest = eboot_dir / "fakelib"
            
            try:
                # Remove existing fakelib if it exists
                if fakelib_dest.exists():
                    shutil.rmtree(fakelib_dest)
                
                # Copy fakelib directory
                shutil.copytree(fakelib_source, fakelib_dest)
                
                results['created'] += 1
                results['locations'].append(str(fakelib_dest))
                
                if verbose:
                    self._print(f"  ✓ Copied fakelib to: {fakelib_dest.relative_to(output_dir)}", GREEN)
                    
            except Exception as e:
                if verbose:
                    self._print(f"  ✗ Failed to copy fakelib to {eboot_dir.relative_to(output_dir)}: {str(e)[:50]}", RED)
        
        return results
    
    def _save_directories_to_config(self, input_dir: str, output_dir: str):
        """Save input and output directories to configuration file."""
        config = self._load_config()
        
        # Update directories in config
        config['directories'] = {
            'last_input': input_dir,
            'last_output': output_dir,
            'last_used': self._get_timestamp()
        }
        
        # Save config
        self._save_config(config)
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        config_path = self.project_root / CONFIG_FILE
        
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        # Default config
        return {
            'directories': {
                'last_input': '',
                'last_output': '',
                'last_used': ''
            }
        }
    
    def _save_config(self, config: Dict[str, Any]):
        """Save configuration to file."""
        config_path = self.project_root / CONFIG_FILE
        
        try:
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
        except:
            pass
    
    def get_last_directories(self) -> Tuple[str, str]:
        """Get last used input and output directories from config."""
        config = self._load_config()
        dirs = config.get('directories', {})
        return dirs.get('last_input', ''), dirs.get('last_output', '')
    
    def _get_timestamp(self) -> str:
        """Get current timestamp for results."""
        import time
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


# Interactive CLI functions
def print_banner():
    """Print a banner for the tool."""
    banner = f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════════════════════╗
║                           PS5 Backport Tool                          ║
║               SDK Downgrade + Fake Sign + Decrypt Functions          ║
╚══════════════════════════════════════════════════════════════════════╝{RESET}
"""
    print(banner)

def get_sdk_version_choice() -> int:
    """Prompt user to select an SDK version pair."""
    pairs = SDKVersionPatcher.get_supported_pairs()
    
    print(f"{CYAN}Available SDK Version Pairs:{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    print(f"{BOLD}{'Pair':<6} {'PS5 SDK Version':<20} {'PS4 Version':<20}{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    for pair_num, (ps5_ver, ps4_ver) in pairs.items():
        print(f"  {pair_num:<4} 0x{ps5_ver:08X}{' ' * 10}0x{ps4_ver:08X}")
    
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    while True:
        try:
            choice = input(f"\n{CYAN}Enter SDK version pair number (1-{len(pairs)}): {RESET}").strip()
            if not choice:
                print(f"{YELLOW}Using default: Pair 4 (0x04000031, 0x09040001){RESET}")
                return 4
            
            choice_num = int(choice)
            if choice_num in pairs:
                return choice_num
            else:
                print(f"{RED}Invalid choice. Please select a number between 1 and {len(pairs)}.{RESET}")
        except ValueError:
            print(f"{RED}Invalid input. Please enter a number.{RESET}")

def get_paid_choice() -> int:
    """Prompt user to select PAID (Program Authentication ID)."""
    paid_options = {
        1: ("Fake Paid (Default)", 0x3100000000000002),
        2: ("System Paid", 0x3200000000000001),
        3: ("NPDRM Paid", 0x3300000000000003),
        4: ("Custom Paid", None)
    }
    
    print(f"\n{CYAN}Available PAID (Program Authentication ID) Options:{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    print(f"{BOLD}{'Option':<8} {'Description':<30} {'Value':<20}{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    for option_num, (desc, value) in paid_options.items():
        if value:
            print(f"  {option_num:<6} {desc:<30} 0x{value:016X}")
        else:
            print(f"  {option_num:<6} {desc:<30} (custom input)")
    
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    while True:
        try:
            choice = input(f"\n{CYAN}Select PAID option (1-4, default=1): {RESET}").strip()
            if not choice:
                print(f"{YELLOW}Using default: Fake Paid (0x3100000000000002){RESET}")
                return paid_options[1][1]
            
            choice_num = int(choice)
            if choice_num in paid_options:
                if choice_num == 4:
                    while True:
                        try:
                            custom_paid = input(f"{CYAN}Enter custom PAID (hex, e.g., 0x3200000000000001): {RESET}").strip()
                            if custom_paid.startswith('0x'):
                                custom_paid = int(custom_paid, 16)
                            else:
                                custom_paid = int(custom_paid, 0)
                            
                            if 0 <= custom_paid <= 0xFFFFFFFFFFFFFFFF:
                                return custom_paid
                            else:
                                print(f"{RED}PAID must be a 64-bit value (0-0xFFFFFFFFFFFFFFFF){RESET}")
                        except ValueError:
                            print(f"{RED}Invalid hex value. Try again.{RESET}")
                else:
                    return paid_options[choice_num][1]
            else:
                print(f"{RED}Invalid choice. Please select 1-4.{RESET}")
        except ValueError:
            print(f"{RED}Invalid input. Please enter a number.{RESET}")

def get_ptype_choice() -> int:
    """Prompt user to select program type."""
    ptype_options = {
        1: ("Fake (Default)", 1),  # FakeSignedELFConverter.parse_ptype('fake') returns 1
        2: ("NPDRM Executable", 4),  # FakeSignedELFConverter.parse_ptype('npdrm_exec')
        3: ("NPDRM Dynamic Library", 5),  # FakeSignedELFConverter.parse_ptype('npdrm_dynlib')
        4: ("System Executable", 8),  # FakeSignedELFConverter.parse_ptype('system_exec')
        5: ("System Dynamic Library", 9),  # FakeSignedELFConverter.parse_ptype('system_dynlib')
        6: ("Custom PType", None)
    }
    
    print(f"\n{CYAN}Available Program Type Options:{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    print(f"{BOLD}{'Option':<8} {'Description':<30} {'Value':<20}{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    for option_num, (desc, value) in ptype_options.items():
        if value is not None:
            print(f"  {option_num:<6} {desc:<30} 0x{value:08X}")
        else:
            print(f"  {option_num:<6} {desc:<30} (custom input)")
    
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    while True:
        try:
            choice = input(f"\n{CYAN}Select program type (1-6, default=1): {RESET}").strip()
            if not choice:
                print(f"{YELLOW}Using default: Fake (0x1){RESET}")
                return ptype_options[1][1]
            
            choice_num = int(choice)
            if choice_num in ptype_options:
                if choice_num == 6:
                    while True:
                        try:
                            custom_ptype = input(f"{CYAN}Enter custom PType (hex or name): {RESET}").strip()
                            # Try to parse as hex first
                            try:
                                if custom_ptype.startswith('0x'):
                                    ptype_value = int(custom_ptype, 16)
                                else:
                                    ptype_value = int(custom_ptype, 0)
                            except ValueError:
                                # Try to parse as string
                                try:
                                    ptype_value = FakeSignedELFConverter.parse_ptype(custom_ptype.lower())
                                except Exception:
                                    raise ValueError(f"Unknown program type: {custom_ptype}")
                            
                            if 0 <= ptype_value <= 0xFFFFFFFF:
                                return ptype_value
                            else:
                                print(f"{RED}PType must be a 32-bit value (0-0xFFFFFFFF){RESET}")
                        except Exception as e:
                            print(f"{RED}{str(e)}. Try again or use 'fake', 'npdrm_exec', etc.{RESET}")
                else:
                    return ptype_options[choice_num][1]
            else:
                print(f"{RED}Invalid choice. Please select 1-6.{RESET}")
        except ValueError:
            print(f"{RED}Invalid input. Please enter a number.{RESET}")

def get_operation_choice() -> str:
    """Prompt user to select operation mode."""
    operations = {
        '1': 'decrypt_and_sign_pipeline',  # DEFAULT
        '2': 'downgrade_and_sign',
        '3': 'decrypt_only',
        '4': 'downgrade_and_sign'  # Legacy alias for backward compatibility
    }
    
    print(f"\n{CYAN}Available Operations:{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    print(f"{BOLD}{'Option':<8} {'Description':<40}{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    print(f"  1       Auto-detect pipeline (decrypt SELF, sign everything) - DEFAULT")
    print(f"  2       Downgrade and sign only (convert ELF to SELF)")
    print(f"  3       Decrypt only (convert SELF to ELF)")
    print(f"  4       Legacy pipeline (for backward compatibility)")
    
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    while True:
        choice = input(f"\n{CYAN}Select operation (1-4, default=1): {RESET}").strip()
        if not choice:
            print(f"{YELLOW}Using default: Auto-detect pipeline{RESET}")
            return 'decrypt_and_sign_pipeline'
        
        if choice in operations:
            return operations[choice]
        else:
            print(f"{RED}Invalid choice. Please select 1-4.{RESET}")

def get_fakelib_choice(project_root: Path, args_fakelib: Optional[str] = None) -> Optional[Path]:
    """Prompt user to select or specify fakelib directory."""
    if args_fakelib:
        fakelib_path = Path(args_fakelib)
        if fakelib_path.exists() and fakelib_path.is_dir():
            return fakelib_path
        else:
            print(f"{YELLOW}Warning: Custom fakelib directory does not exist: {fakelib_path}{RESET}")
            print(f"{YELLOW}Falling back to interactive selection{RESET}")
    
    default_fakelib = project_root / "fakelib"
    
    print(f"\n{CYAN}Fakelib Directory Options:{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    print(f"{BOLD}{'Option':<8} {'Description':<40}{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    print(f"  1       Use default fakelib ({default_fakelib})")
    print(f"  2       Use custom fakelib directory")
    print(f"  3       Skip fakelib copy")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    while True:
        choice = input(f"\n{CYAN}Select fakelib option (1-3, default=1): {RESET}").strip()
        if not choice:
            print(f"{YELLOW}Using default: Use default fakelib{RESET}")
            return default_fakelib if default_fakelib.exists() else None
        
        if choice == '1':
            if default_fakelib.exists() and default_fakelib.is_dir():
                return default_fakelib
            else:
                print(f"{YELLOW}Default fakelib not found at {default_fakelib}{RESET}")
                return None
        elif choice == '2':
            while True:
                custom_path = input(f"{CYAN}Enter custom fakelib directory: {RESET}").strip()
                if not custom_path:
                    print(f"{YELLOW}Using default fakelib instead{RESET}")
                    return default_fakelib if default_fakelib.exists() else None
                
                fakelib_path = Path(custom_path)
                if fakelib_path.exists() and fakelib_path.is_dir():
                    return fakelib_path
                else:
                    print(f"{RED}Error: Directory does not exist or is not a directory: {fakelib_path}{RESET}")
                    print(f"{YELLOW}Please enter a valid directory path{RESET}")
        elif choice == '3':
            print(f"{YELLOW}Skipping fakelib copy{RESET}")
            return None
        else:
            print(f"{RED}Invalid choice. Please select 1-3.{RESET}")

def get_input_directory_with_memory(processor: PS5ELFProcessor) -> Path:
    """Get input directory with memory of last used directory."""
    last_input, last_output = processor.get_last_directories()
    
    if last_input and Path(last_input).exists():
        print(f"{CYAN}Last used input directory: {last_input}{RESET}")
        use_last = input(f"{CYAN}Use this directory? (Y/n): {RESET}").strip().lower()
        if use_last in ['', 'y', 'yes']:
            return Path(last_input)
    
    while True:
        input_path = input(f"{CYAN}Enter input directory: {RESET}").strip()
        if not input_path:
            print(f"{RED}Error: Input directory is required{RESET}")
            continue
        
        input_dir = Path(input_path)
        if not input_dir.exists():
            print(f"{RED}Error: Input directory does not exist: {input_dir}{RESET}")
            continue
        
        if not input_dir.is_dir():
            print(f"{RED}Error: Input path is not a directory: {input_dir}{RESET}")
            continue
        
        return input_dir

def get_output_directory_with_memory(processor: PS5ELFProcessor) -> Path:
    """Get output directory with memory of last used directory."""
    last_input, last_output = processor.get_last_directories()
    
    if last_output and Path(last_output).exists():
        print(f"{CYAN}Last used output directory: {last_output}{RESET}")
        use_last = input(f"{CYAN}Use this directory? (Y/n): {RESET}").strip().lower()
        if use_last in ['', 'y', 'yes']:
            return Path(last_output)
    
    while True:
        output_path = input(f"{CYAN}Enter output directory: {RESET}").strip()
        if not output_path:
            print(f"{RED}Error: Output directory is required{RESET}")
            continue
        
        output_dir = Path(output_path)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            return output_dir
        except Exception as e:
            print(f"{RED}Error creating output directory: {str(e)}{RESET}")

def print_summary(results: Dict[str, Dict[str, any]], output_dir: Path, operation: str):
    """Print a summary of the processing results."""
    print(f"\n{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")
    print(f"{CYAN}{BOLD}                      PROCESSING SUMMARY                     {RESET}")
    print(f"{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")
    
    operation_display = {
        'decrypt_and_sign_pipeline': 'Auto-detect Pipeline',
        'downgrade_and_sign': 'Downgrade & Sign',
        'decrypt_only': 'Decrypt Only'
    }
    
    print(f"\n{BOLD}Operation:{RESET} {operation_display.get(operation, operation)}")
    
    if 'detection' in results:
        detection = results['detection']
        print(f"\n{BOLD}File Detection:{RESET}")
        print(f"  {CYAN}SELF files: {detection['self_files']}{RESET}")
        print(f"  {CYAN}ELF files: {detection['elf_files']}{RESET}")
        print(f"  {CYAN}Other files: {detection['other_files']}{RESET}")
    
    if 'decrypt' in results:
        decrypt = results['decrypt']
        print(f"\n{BOLD}Decryption Results:{RESET}")
        print(f"  {GREEN}Successful: {decrypt['successful']}{RESET}")
        print(f"  {RED if decrypt['failed'] > 0 else YELLOW}Failed: {decrypt['failed']}{RESET}")
        print(f"  {CYAN}Total: {decrypt['successful'] + decrypt['failed']}{RESET}")
        
        if 'error' in decrypt:
            print(f"  {RED}Error: {decrypt['error']}{RESET}")
    
    if 'downgrade' in results:
        downgrade = results['downgrade']
        print(f"\n{BOLD}Downgrade Results:{RESET}")
        print(f"  {GREEN}Successful: {downgrade['successful']}{RESET}")
        print(f"  {RED if downgrade['failed'] > 0 else YELLOW}Failed: {downgrade['failed']}{RESET}")
        print(f"  {CYAN}Total: {downgrade['successful'] + downgrade['failed']}{RESET}")
    
    if 'signing' in results:
        signing = results['signing']
        print(f"\n{BOLD}Signing Results:{RESET}")
        print(f"  {GREEN}Successful: {signing['successful']}{RESET}")
        print(f"  {RED if signing['failed'] > 0 else YELLOW}Failed: {signing['failed']}{RESET}")
        print(f"  {CYAN}Total: {signing['successful'] + signing['failed']}{RESET}")
    
    if 'libc_patch' in results:
        patch = results['libc_patch']
        if patch.get('applied', 0) > 0:
            print(f"\n{BOLD}libc.prx Patch Results:{RESET}")
            print(f"  {GREEN}Files patched: {patch['applied']}{RESET}")
            if patch.get('results'):
                print(f"  {CYAN}Details: {len(patch['results'])} file(s) processed{RESET}")
        elif patch.get('reverted', 0) > 0:
            print(f"\n{BOLD}libc.prx Patch Results:{RESET}")
            print(f"  {GREEN}Files reverted: {patch['reverted']}{RESET}")
            if patch.get('results'):
                print(f"  {CYAN}Details: {len(patch['results'])} file(s) processed{RESET}")
        elif 'results' in patch and patch['results']:
            print(f"\n{BOLD}libc.prx Patch Results:{RESET}")
            print(f"  {YELLOW}No files were patched or reverted{RESET}")
    
    if 'fakelib' in results:
        fakelib = results['fakelib']
        if fakelib.get('message'):
            print(f"\n{BOLD}Fakelib Copy:{RESET}")
            if fakelib.get('success', False):
                print(f"  {GREEN}✓ {fakelib['message']}{RESET}")
            else:
                print(f"  {YELLOW}⚠ {fakelib['message']}{RESET}")
    
    # Show fakelib copies to eboot.bin directories
    if 'fakelib_copies' in results:
        fakelib_copies = results['fakelib_copies']
        if fakelib_copies.get('created', 0) > 0:
            print(f"\n{BOLD}Fakelib Copies to eboot.bin directories:{RESET}")
            print(f"  {GREEN}Created: {fakelib_copies['created']} copy(ies){RESET}")
            for i, location in enumerate(fakelib_copies.get('locations', [])[:3]):
                print(f"  {CYAN}  • {Path(location).relative_to(Path(results.get('output_dir', '')))}{RESET}")
            if len(fakelib_copies.get('locations', [])) > 3:
                print(f"  {CYAN}  ... and {len(fakelib_copies['locations']) - 3} more{RESET}")
    
    # Show decrypted folder location
    if 'decrypted_folder' in results and results['decrypted_folder']:
        print(f"\n{BOLD}Decrypted Files:{RESET}")
        print(f"  {CYAN}Saved to: {results['decrypted_folder']}{RESET}")
    
    # List failed files if any
    failed_files = []
    
    if 'decrypt' in results:
        failed_files.extend([(f, 'Decryption', data.get('message', 'Unknown error'))
                           for f, data in results['decrypt']['files'].items() 
                           if not data.get('success', False)])
    
    if 'downgrade' in results:
        failed_files.extend([(f, 'Downgrade', data.get('message', 'Unknown error'))
                           for f, data in results['downgrade']['files'].items() 
                           if not data.get('success', False)])
    
    if 'signing' in results:
        failed_files.extend([(f, 'Signing', data.get('message', 'Unknown error'))
                           for f, data in results['signing']['files'].items() 
                           if not data.get('success', False)])
    
    if failed_files:
        print(f"\n{BOLD}Failed Files (first 5 shown):{RESET}")
        for f, op, msg in failed_files[:5]:
            filename = Path(f).name
            print(f"  {RED}• [{op}] {filename}: {msg[:100]}{'...' if len(msg) > 100 else ''}{RESET}")
        if len(failed_files) > 5:
            print(f"  {YELLOW}... and {len(failed_files) - 5} more{RESET}")
    
    print(f"\n{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")
    print(f"{GREEN}{BOLD}Processing complete! Output directory: {output_dir}{RESET}")
    print(f"{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")

def run_interactive_cli():
    """Run the full interactive CLI with prompts."""
    print_banner()
    
    # Initialize processor
    processor = PS5ELFProcessor(use_colors=True)
    
    # Get operation mode
    operation = get_operation_choice()
    
    # Get input directory (with memory)
    input_dir = get_input_directory_with_memory(processor)
    
    # Get output directory (with memory)
    output_dir = get_output_directory_with_memory(processor)
    
    # Find project root
    project_root = Path(__file__).parent
    
    # Get fakelib directory if needed
    fakelib_source = None
    if operation in ['decrypt_and_sign_pipeline', 'downgrade_and_sign']:
        fakelib_source = get_fakelib_choice(project_root)
    
    # Get configuration based on operation mode
    sdk_pair = None
    paid = None
    ptype = None
    
    if operation in ['decrypt_and_sign_pipeline', 'downgrade_and_sign']:
        # Get SDK version pair
        sdk_pair = get_sdk_version_choice()
        
        # Get PAID
        paid = get_paid_choice()
        
        # Get PType
        ptype = get_ptype_choice()
    
    # Print configuration
    print(f"\n{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")
    print(f"{CYAN}{BOLD}                      CONFIGURATION                         {RESET}")
    print(f"{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")
    print(f"  {BOLD}Operation:{RESET} {operation.replace('_', ' ').title()}")
    print(f"  {BOLD}Input Directory:{RESET} {input_dir}")
    print(f"  {BOLD}Output Directory:{RESET} {output_dir}")
    
    if fakelib_source:
        print(f"  {BOLD}Fakelib Source:{RESET} {fakelib_source}")
    else:
        print(f"  {BOLD}Fakelib Source:{RESET} None (will skip)")
    
    if operation in ['decrypt_and_sign_pipeline', 'downgrade_and_sign']:
        pairs = SDKVersionPatcher.get_supported_pairs()
        ps5_sdk_version, ps4_version = pairs[sdk_pair]
        print(f"  {BOLD}SDK Version Pair:{RESET} {sdk_pair} (PS5: 0x{ps5_sdk_version:08X}, PS4: 0x{ps4_version:08X})")
        print(f"  {BOLD}PAID:{RESET} 0x{paid:016X}")
        print(f"  {BOLD}PType:{RESET} 0x{ptype:08X}")
        
        # Special note for SDK pair 6 or below
        if sdk_pair <= 6:
            print(f"  {YELLOW}{BOLD}Note:{RESET} SDK pair {sdk_pair} selected - will apply libc.prx patch after signing{RESET}")
    
    print(f"{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")
    
    # Confirm before proceeding
    confirm = input(f"\n{CYAN}Proceed with processing? (y/N): {RESET}").strip().lower()
    if confirm not in ['y', 'yes']:
        print(f"{YELLOW}Processing cancelled.{RESET}")
        sys.exit(0)
    
    # Process files based on operation
    try:
        if operation == 'decrypt_only':
            results = processor.decrypt_files(
                input_dir=input_dir,
                output_dir=output_dir,
                overwrite=False,
                verbose=True
            )
        
        elif operation == 'downgrade_and_sign':
            results = processor.downgrade_and_sign(
                input_dir=input_dir,
                output_dir=output_dir,
                sdk_pair=sdk_pair,
                paid=paid,
                ptype=ptype,
                fakelib_source=fakelib_source,
                create_backup=True,
                overwrite=False,
                apply_libc_patch=True,
                auto_revert_for_high_sdk=True,
                verbose=True
            )
        
        elif operation == 'decrypt_and_sign_pipeline':
            results = processor.decrypt_and_sign_pipeline(
                input_dir=input_dir,
                output_dir=output_dir,
                sdk_pair=sdk_pair,
                paid=paid,
                ptype=ptype,
                fakelib_source=fakelib_source,
                create_backup=True,
                overwrite=False,
                apply_libc_patch=True,
                auto_revert_for_high_sdk=True,
                verbose=True
            )
        
        else:
            print(f"{RED}Error: Unknown operation: {operation}{RESET}")
            sys.exit(1)
        
        # Print summary
        print_summary(results, output_dir, operation)
        
        # Exit with appropriate code
        has_failures = any(
            results.get(key, {}).get('failed', 0) > 0 
            for key in ['decrypt', 'downgrade', 'signing']
            if key in results
        )
        
        if has_failures:
            print(f"\n{YELLOW}Warning: Some files failed to process{RESET}")
            sys.exit(1)
        else:
            print(f"\n{GREEN}All files processed successfully!{RESET}")
            sys.exit(0)
            
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Processing interrupted by user.{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Unexpected error: {str(e)}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# Utility functions for common operations
def decrypt_file(
    input_file: Union[str, Path],
    output_file: Union[str, Path],
    verbose: bool = False
) -> bool:
    """
    Convenience function to decrypt a single SELF file.
    
    Args:
        input_file: Path to input SELF file
        output_file: Path to output ELF file
        verbose: Print progress information
        
    Returns:
        True if successful
    """
    processor = PS5ELFProcessor(use_colors=False)
    
    # Use processor's internal method
    converter = UnsignedELFConverter(verbose=verbose)
    return converter.convert_file(str(input_file), str(output_file))


def sign_file(
    input_file: Union[str, Path],
    output_file: Union[str, Path],
    sdk_pair: int = 4,
    paid: int = 0x3100000000000002,
    ptype: int = 1,
    verbose: bool = False
) -> bool:
    """
    Convenience function to sign a single ELF file.
    
    Args:
        input_file: Path to input ELF file
        output_file: Path to output SELF file
        sdk_pair: SDK version pair number
        paid: Program Authentication ID
        ptype: Program type
        verbose: Print progress information
        
    Returns:
        True if successful
    """
    # Create temporary directory for processing
    temp_dir = Path(tempfile.mkdtemp(prefix="ps5_elf_"))
    
    try:
        processor = PS5ELFProcessor(use_colors=False)
        
        # Copy input file to temp directory
        temp_input = temp_dir / Path(input_file).name
        shutil.copy2(input_file, temp_input)
        
        # Create temp output directory
        temp_output = temp_dir / "output"
        
        # Process the single file
        results = processor.downgrade_and_sign(
            input_dir=temp_dir,
            output_dir=temp_output,
            sdk_pair=sdk_pair,
            paid=paid,
            ptype=ptype,
            fakelib_source=None,
            create_backup=False,
            overwrite=True,
            apply_libc_patch=False,
            auto_revert_for_high_sdk=True,
            verbose=verbose,
            save_to_config=False
        )
        
        # Check if successful
        if results['signing']['successful'] > 0:
            # Find the output file
            for file_info in results['signing']['files'].values():
                if file_info.get('success', False):
                    output_path = file_info.get('output', '')
                    if output_path:
                        # Copy to final location
                        output_dir = Path(output_file).parent
                        output_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(output_path, output_file)
                        return True
        
        return False
        
    finally:
        # Clean up temporary directory
        try:
            shutil.rmtree(temp_dir)
        except:
            pass


def get_sdk_version_info() -> Dict[int, Tuple[int, int]]:
    """Get all supported SDK version pairs."""
    processor = PS5ELFProcessor(use_colors=False)
    return processor.get_supported_sdk_pairs()


def get_default_fakelib_path(project_root: Optional[Union[str, Path]] = None) -> Optional[Path]:
    """Get default fakelib path if it exists."""
    if project_root is None:
        project_root = Path(__file__).parent
    
    project_root = Path(project_root)
    fakelib_path = project_root / "fakelib"
    
    if fakelib_path.exists() and fakelib_path.is_dir():
        return fakelib_path
    return None


# CLI Interface
def run_cli():
    """Command-line interface for the PS5 Backport Tool."""
    parser = argparse.ArgumentParser(
        description='PS5 Backport Tool - Downgrade, fake sign, and decrypt ELF/SELF files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Interactive mode with prompts (full CLI):
    python Backport.py -c
  
  Direct command mode (AUTO is default):
    python Backport.py --mode auto --input input/ --output output/ --sdk-pair 4
    python Backport.py --mode decrypt --input encrypted/ --output decrypted/
    python Backport.py --mode downgrade --input decrypted/ --output signed/ --sdk-pair 4
  
  Auto mode (default) - automatically detects SELF/ELF files:
    python Backport.py --input input/ --output output/ --sdk-pair 4
  
  Libc patch operations (on SELF files OR single files):
    # Check status of a single file
    python Backport.py --mode libc-patch --input libc.prx --action check
    
    # Check status of all files in a directory
    python Backport.py --mode libc-patch --input signed/ --action check
    
    # Apply patch to a single file
    python Backport.py --mode libc-patch --input libc.prx --action apply
    
    # Apply patch to all files in a directory
    python Backport.py --mode libc-patch --input signed/ --action apply
    
    # Revert patch from a single file
    python Backport.py --mode libc-patch --input libc.prx --action revert
    
    # Revert patch from all files in a directory
    python Backport.py --mode libc-patch --input signed/ --action revert
  
  With custom fakelib:
    python Backport.py --input in/ --output out/ --sdk-pair 4 --fakelib /path/to/fakelib
  
  List available SDK pairs:
    python Backport.py --list-sdk-pairs
        """
    )
    
    # Interactive mode flag
    parser.add_argument(
        '-c', '--cli',
        action='store_true',
        help='Run in interactive CLI mode (with prompts)'
    )
    
    # Main operation mode
    parser.add_argument(
        '--mode', '-m',
        type=str,
        choices=['auto', 'decrypt', 'downgrade', 'libc-patch'],
        default='auto',  # AUTO IS NOW DEFAULT
        help='Operation mode: auto (detect file type), decrypt (SELF to ELF), downgrade (ELF to SELF), libc-patch (libc operations)'
    )
    
    # Libc patch specific arguments
    parser.add_argument(
        '--action',
        type=str,
        choices=['apply', 'revert', 'check'],
        help='Action for libc-patch mode: apply, revert, or check status'
    )
    
    # Input arguments (can be file or directory)
    parser.add_argument(
        '--input', '-i',
        type=str,
        help='Input directory OR file containing files'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='Output directory for processed files (not used for libc-patch)'
    )
    
    # Downgrade-specific arguments
    parser.add_argument(
        '--sdk-pair', '-s',
        type=int,
        default=4,
        help='SDK version pair number (1-10, default: 4)'
    )
    
    parser.add_argument(
        '--paid',
        type=str,
        default='0x3100000000000002',
        help='Program Authentication ID (hex, default: 0x3100000000000002)'
    )
    
    parser.add_argument(
        '--ptype',
        type=str,
        default='fake',
        help='Program type (name or hex, default: "fake")'
    )
    
    # Libc patch behavior
    parser.add_argument(
        '--no-libc-patch',
        action='store_true',
        help='Skip libc.prx patch entirely (even for SDK ≤ 6)'
    )
    
    parser.add_argument(
        '--no-auto-revert',
        action='store_true',
        help='Do not automatically revert libc patch for SDK > 6'
    )
    
    # Fakelib argument
    parser.add_argument(
        '--fakelib', '-f',
        type=str,
        help='Custom fakelib directory path (optional)'
    )
    
    # Common arguments
    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Do not create backup files during downgrade'
    )
    
    parser.add_argument(
        '--no-colors',
        action='store_true',
        help='Disable colored output'
    )
    
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite existing files'
    )
    
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress output'
    )
    
    parser.add_argument(
        '--list-sdk-pairs',
        action='store_true',
        help='List available SDK version pairs and exit'
    )
    
    args = parser.parse_args()
    
    # Run interactive CLI if requested
    if args.cli:
        run_interactive_cli()
        return
    
    # List SDK pairs if requested
    if args.list_sdk_pairs:
        sdk_pairs = get_sdk_version_info()
        print("Available SDK Version Pairs:")
        print("┌──────┬──────────────────────┬──────────────────────┐")
        print("│ Pair │ PS5 SDK Version      │ PS4 Version         │")
        print("├──────┼──────────────────────┼──────────────────────┤")
        for pair_num, (ps5_ver, ps4_ver) in sdk_pairs.items():
            print(f"│ {pair_num:<4} │ 0x{ps5_ver:08X}            │ 0x{ps4_ver:08X}           │")
        print("└──────┴──────────────────────┴──────────────────────┘")
        sys.exit(0)
    
    # Validate arguments based on mode
    if args.mode == 'libc-patch':
        if not args.action:
            print("Error: --action is required for libc-patch mode")
            sys.exit(1)
        if not args.input:
            print("Error: --input is required for libc-patch mode")
            sys.exit(1)
    elif args.mode in ['auto', 'decrypt', 'downgrade']:
        if not args.input:
            print(f"Error: --input is required for {args.mode} mode")
            sys.exit(1)
        if not args.output:
            print(f"Error: --output is required for {args.mode} mode")
            sys.exit(1)
    else:
        print("Error: Invalid mode specified")
        sys.exit(1)
    
    # Initialize processor
    processor = PS5ELFProcessor(use_colors=not args.no_colors)
    
    # Process based on mode
    try:
        if args.mode == 'decrypt':
            results = processor.decrypt_files(
                input_dir=args.input,
                output_dir=args.output,
                overwrite=args.overwrite,
                verbose=not args.quiet
            )
            
        elif args.mode == 'downgrade':
            # Parse ptype
            try:
                if args.ptype.startswith('0x'):
                    ptype = int(args.ptype, 16)
                else:
                    try:
                        ptype = int(args.ptype, 0)
                    except ValueError:
                        ptype = processor.parse_ptype(args.ptype.lower())
            except Exception as e:
                print(f"Error: Invalid ptype '{args.ptype}': {str(e)}")
                sys.exit(1)
            
            # Parse paid
            try:
                if args.paid.startswith('0x'):
                    paid = int(args.paid, 16)
                else:
                    paid = int(args.paid, 0)
            except ValueError:
                print(f"Error: Invalid PAID format. Use hex (0x...) or decimal")
                sys.exit(1)
            
            # Get fakelib path
            fakelib_source = None
            if args.fakelib:
                fakelib_source = args.fakelib
            else:
                default_fakelib = get_default_fakelib_path()
                if default_fakelib:
                    fakelib_source = str(default_fakelib)
            
            results = processor.downgrade_and_sign(
                input_dir=args.input,
                output_dir=args.output,
                sdk_pair=args.sdk_pair,
                paid=paid,
                ptype=ptype,
                fakelib_source=fakelib_source,
                create_backup=not args.no_backup,
                overwrite=args.overwrite,
                apply_libc_patch=not args.no_libc_patch,
                auto_revert_for_high_sdk=not args.no_auto_revert,
                verbose=not args.quiet
            )
            
        elif args.mode == 'auto':
            # Parse ptype
            try:
                if args.ptype.startswith('0x'):
                    ptype = int(args.ptype, 16)
                else:
                    try:
                        ptype = int(args.ptype, 0)
                    except ValueError:
                        ptype = processor.parse_ptype(args.ptype.lower())
            except Exception as e:
                print(f"Error: Invalid ptype '{args.ptype}': {str(e)}")
                sys.exit(1)
            
            # Parse paid
            try:
                if args.paid.startswith('0x'):
                    paid = int(args.paid, 16)
                else:
                    paid = int(args.paid, 0)
            except ValueError:
                print(f"Error: Invalid PAID format. Use hex (0x...) or decimal")
                sys.exit(1)
            
            # Get fakelib path
            fakelib_source = None
            if args.fakelib:
                fakelib_source = args.fakelib
            else:
                default_fakelib = get_default_fakelib_path()
                if default_fakelib:
                    fakelib_source = str(default_fakelib)
            
            results = processor.decrypt_and_sign_pipeline(
                input_dir=args.input,
                output_dir=args.output,
                sdk_pair=args.sdk_pair,
                paid=paid,
                ptype=ptype,
                fakelib_source=fakelib_source,
                create_backup=not args.no_backup,
                overwrite=args.overwrite,
                apply_libc_patch=not args.no_libc_patch,
                auto_revert_for_high_sdk=not args.no_auto_revert,
                verbose=not args.quiet,
                save_to_config=True
            )
            
        elif args.mode == 'libc-patch':
            if not args.action:
                print("Error: --action is required for libc-patch mode")
                sys.exit(1)
            if not args.input:
                print("Error: --input is required for libc-patch mode")
                sys.exit(1)
            
            input_path = Path(args.input)
            
            # For apply/revert, we need to check if input exists
            if not input_path.exists():
                print(f"Error: Input path does not exist: {args.input}")
                sys.exit(1)
            
            # Handle single file vs directory
            if input_path.is_file():
                if not (processor._is_self_file(input_path) or 'libc' in input_path.name.lower()):
                    print(f"Warning: Input file may not be a SELF or libc file")
                    # Ask for confirmation only if not quiet
                    if not args.quiet:
                        confirm = input("Continue anyway? (y/N): ").strip().lower()
                        if confirm not in ['y', 'yes']:
                            print("Aborted")
                            sys.exit(0)
            
            if args.action == 'apply':
                results = processor.apply_libc_patch(
                    input_dir=args.input,  # This works for both files and directories
                    create_backup=True,
                    verbose=not args.quiet
                )
            elif args.action == 'revert':
                results = processor.revert_libc_patch(
                    input_dir=args.input,  # This works for both files and directories
                    create_backup=True,
                    verbose=not args.quiet
                )
            elif args.action == 'check':
                results = processor.check_libc_patch_status(
                    input_path=args.input,  # This works for both files and directories
                    verbose=not args.quiet
                )
        
        # Print summary
        if not args.quiet:
            print(f"\nProcessing complete!")
            
            if 'operation' in results:
                print(f"Operation: {results['operation'].replace('_', ' ').title()}")
            
            if 'detection' in results:
                detection = results['detection']
                print(f"File detection: {detection['self_files']} SELF, {detection['elf_files']} ELF")
            
            if 'decrypted_folder' in results and results['decrypted_folder']:
                print(f"Decrypted files saved to: {results['decrypted_folder']}")
            
            if 'successful' in results:
                print(f"Successful: {results['successful']}")
            
            if 'failed' in results:
                print(f"Failed: {results['failed']}")
            
            if 'applied' in results and results['applied'] > 0:
                print(f"Libc patches applied: {results['applied']}")
            
            if 'reverted' in results and results['reverted'] > 0:
                print(f"Libc patches reverted: {results['reverted']}")
            
            # Show fakelib copies
            if 'fakelib_copies' in results and results['fakelib_copies'].get('created', 0) > 0:
                print(f"Fakelib copies to eboot.bin dirs: {results['fakelib_copies']['created']}")
            
            if 'output_dir' in results:
                print(f"Output: {results['output_dir']}")
            
            # Special note for auto/downgrade operations
            if args.mode in ['auto', 'downgrade']:
                print(f"\nNote: All output files are in SELF format")
                if not args.no_libc_patch:
                    if args.sdk_pair <= 6:
                        print(f"Libc.prx patch was applied to SELF files (SDK ≤ 6)")
                    elif not args.no_auto_revert:
                        print(f"Libc.prx patch was reverted if found (SDK > 6)")
        
        # Exit with appropriate code
        if results.get('failed', 0) > 0:
            sys.exit(1)
        else:
            sys.exit(0)
            
    except KeyboardInterrupt:
        print("\nProcessing interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_cli()