#!/usr/bin/env python3

import os
import sys
import shutil
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from src.ps5_sdk_version_patcher import SDKVersionPatcher
from src.make_fself import FakeSignedELFConverter
from src.decrypt_fself import UnsignedELFConverter

# ANSI color codes
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
CYAN = '\033[96m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

def print_banner():
    """Print a banner for the tool."""
    banner = f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════════════════════╗
║             PS5 ELF Processing Tool                          ║
║       SDK Downgrade + Fake Sign + Decrypt Functions          ║
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
        '1': 'downgrade_and_sign',
        '2': 'decrypt_only',
        '3': 'full_pipeline'
    }
    
    print(f"\n{CYAN}Available Operations:{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    print(f"{BOLD}{'Option':<8} {'Description':<40}{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    print(f"  1       Downgrade and sign only (convert ELF to SELF)")
    print(f"  2       Decrypt only (convert SELF to ELF)")
    print(f"  3       Full pipeline (decrypt → downgrade → sign)")
    
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    while True:
        choice = input(f"\n{CYAN}Select operation (1-3, default=1): {RESET}").strip()
        if not choice:
            print(f"{YELLOW}Using default: Downgrade and sign{RESET}")
            return 'downgrade_and_sign'
        
        if choice in operations:
            return operations[choice]
        else:
            print(f"{RED}Invalid choice. Please select 1-3.{RESET}")

def copy_fakelib(source_dir: Path, output_dir: Path) -> Tuple[bool, str]:
    """
    Copy the fakelib directory to the output directory.
    
    Args:
        source_dir: Root project directory containing fakelib
        output_dir: Output directory where fakelib should be copied
        
    Returns:
        Tuple of (success, message)
    """
    fakelib_source = source_dir / "fakelib"
    
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
        return True, f"Copied fakelib directory ({file_count} files)"
    
    except Exception as e:
        return False, f"Failed to copy fakelib: {str(e)}"

def apply_librc_patch(input_dir: Path, use_colors: bool = True) -> Tuple[int, Dict[str, str]]:
    """
    Apply the Perl patch to librc.prx files when SDK pair is 6.
    
    Args:
        input_dir: Directory containing the processed files
        use_colors: Whether to use colored output
        
    Returns:
        Tuple of (patched_count, results_dict)
    """
    results = {}
    patched_count = 0
    
    print(f"\n{BLUE}{BOLD}[Extra Step] Applying librc.prx patch for SDK pair 6{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    # Search recursively for librc.prx files (case-insensitive)
    print(f"  Searching for librc.prx files in {input_dir}...")
    
    # Find all files that might be librc.prx
    potential_files = []
    for root, dirs, files in os.walk(input_dir):
        for filename in files:
            # Look for files that might be librc.prx (case-insensitive)
            file_lower = filename.lower()
            if 'librc' in file_lower and file_lower.endswith('.prx'):
                file_path = Path(root) / filename
                potential_files.append(file_path)
            # Also check for files that are exactly librc.prx (any case)
            elif file_lower == 'librc.prx':
                file_path = Path(root) / filename
                potential_files.append(file_path)
    
    # Also search for files with .prx extension that might contain librc
    for root, dirs, files in os.walk(input_dir):
        for filename in files:
            if filename.lower().endswith('.prx'):
                file_path = Path(root) / filename
                if file_path not in potential_files:
                    potential_files.append(file_path)
    
    if not potential_files:
        print(f"  {YELLOW}No PRX files found in {input_dir}{RESET}")
        return patched_count, results
    
    print(f"  Found {len(potential_files)} potential PRX file(s) to check\n")
    
    # Pattern to search for
    pattern = b'4h6F1LLbTiw#A#B'
    replacement = b'IWIBBdTHit4#A#B'
    
    for prx_path in potential_files:
        relative_path = prx_path.relative_to(input_dir)
        
        try:
            # Read file content
            with open(prx_path, 'rb') as f:
                content = f.read()
            
            # Check if pattern exists
            if pattern in content:
                print(f"  Found pattern in: {relative_path}")
                print(f"    Patching...")
                
                # Create backup
                backup_path = prx_path.with_suffix('.prx.bak')
                shutil.copy2(prx_path, backup_path)
                
                try:
                    # Apply patch
                    patched_content = content.replace(pattern, replacement)
                    
                    # Write patched content
                    with open(prx_path, 'wb') as f:
                        f.write(patched_content)
                    
                    # Verify patch
                    with open(prx_path, 'rb') as f:
                        new_content = f.read()
                    
                    if pattern not in new_content and replacement in new_content:
                        patched_count += 1
                        results[str(prx_path)] = "Patch applied successfully"
                        print(f"    {GREEN}✓ Patch applied successfully{RESET}")
                    else:
                        # Restore from backup
                        shutil.copy2(backup_path, prx_path)
                        results[str(prx_path)] = "Patch verification failed"
                        print(f"    {RED}✗ Patch verification failed{RESET}")
                
                except Exception as e:
                    # Restore from backup on error
                    if backup_path.exists():
                        shutil.copy2(backup_path, prx_path)
                    results[str(prx_path)] = f"Error during patching: {str(e)}"
                    print(f"    {RED}✗ Error: {str(e)[:50]}{RESET}")
                
                # Clean up backup
                if backup_path.exists():
                    try:
                        os.remove(backup_path)
                    except:
                        pass
                    
            else:
                # Pattern not found in this file
                if 'librc' in prx_path.name.lower():
                    results[str(prx_path)] = "Pattern not found in librc.prx"
                    print(f"  {YELLOW}Pattern not found in: {relative_path}{RESET}")
                    
        except Exception as e:
            results[str(prx_path)] = f"Error reading file: {str(e)}"
            print(f"  {RED}Error reading {relative_path}: {str(e)[:50]}{RESET}")
    
    # Also try to search for the pattern in all binary files if no librc.prx found
    if patched_count == 0 and len(potential_files) == 0:
        print(f"  {YELLOW}Searching for pattern in all binary files...{RESET}")
        
        # Search for pattern in all files
        all_files = []
        for root, dirs, files in os.walk(input_dir):
            for filename in files:
                file_path = Path(root) / filename
                # Skip non-binary files based on extension
                if file_path.suffix.lower() in ['.txt', '.log', '.md', '.json', '.xml', '.html', '.py']:
                    continue
                all_files.append(file_path)
        
        print(f"  Checking {len(all_files)} binary file(s) for pattern...")
        
        for file_path in all_files:
            try:
                with open(file_path, 'rb') as f:
                    content = f.read(10000)  # Read first 10KB to check
                
                if pattern in content:
                    relative_path = file_path.relative_to(input_dir)
                    print(f"  Found pattern in: {relative_path}")
                    
                    # Ask user if they want to patch this file
                    if use_colors and not args.batch:
                        response = input(f"    {CYAN}Patch this file? (y/N): {RESET}").strip().lower()
                        if response not in ['y', 'yes']:
                            continue
                    
                    # Create backup
                    backup_path = file_path.with_suffix(file_path.suffix + '.bak')
                    shutil.copy2(file_path, backup_path)
                    
                    # Read entire file
                    with open(file_path, 'rb') as f:
                        full_content = f.read()
                    
                    # Apply patch
                    patched_content = full_content.replace(pattern, replacement)
                    
                    # Write patched content
                    with open(file_path, 'wb') as f:
                        f.write(patched_content)
                    
                    # Verify patch
                    with open(file_path, 'rb') as f:
                        new_content = f.read()
                    
                    if pattern not in new_content and replacement in new_content:
                        patched_count += 1
                        results[str(file_path)] = "Patch applied successfully"
                        print(f"    {GREEN}✓ Patch applied successfully{RESET}")
                    else:
                        # Restore from backup
                        shutil.copy2(backup_path, file_path)
                        results[str(file_path)] = "Patch verification failed"
                        print(f"    {RED}✗ Patch verification failed{RESET}")
                    
                    # Clean up backup
                    if backup_path.exists():
                        try:
                            os.remove(backup_path)
                        except:
                            pass
                            
            except Exception as e:
                # Skip files we can't read
                pass
    
    print(f"\n  {CYAN}Total files patched: {patched_count}{RESET}")
    return patched_count, results

def is_elf_file(file_path: Path) -> bool:
    """
    Check if a file is an ELF file by checking its magic bytes.
    
    Args:
        file_path: Path to the file to check
        
    Returns:
        True if it's an ELF file
    """
    # Skip .bak backup files
    if file_path.name.endswith('.bak'):
        return False
    
    try:
        with open(file_path, 'rb') as f:
            magic = f.read(4)
            return magic == b'\x7FELF'  # ELF magic
    except:
        return False

def is_self_file(file_path: Path) -> bool:
    """
    Check if a file is a SELF file by checking its magic bytes.
    
    Args:
        file_path: Path to the file to check
        
    Returns:
        True if it's a SELF file
    """
    # Skip .bak backup files
    if file_path.name.endswith('.bak'):
        return False
    
    try:
        with open(file_path, 'rb') as f:
            magic = f.read(4)
            # Check for PS4 and PS5 SELF magic
            return magic in [b'\x4F\x15\x3D\x1D', b'\x54\x14\xF5\xEE']
    except:
        return False

def decrypt_files(input_dir: Path, output_dir: Path, use_colors: bool = True) -> Dict[str, Dict[str, any]]:
    """
    Decrypt SELF files back to ELF files.
    
    Args:
        input_dir: Directory containing SELF files
        output_dir: Directory for output ELF files
        use_colors: Whether to use colored output
        
    Returns:
        Dictionary with processing results
    """
    
    results = {
        'decrypt': {'successful': 0, 'failed': 0, 'files': {}}
    }
    
    print(f"\n{BLUE}{BOLD}[Step 1/1] Decrypting SELF Files{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    # Create converter instance
    converter = UnsignedELFConverter(verbose=use_colors)
    
    # Find all SELF files in input directory, skipping .bak files
    self_files = []
    for root, dirs, files in os.walk(input_dir):
        for filename in files:
            file_path = Path(root) / filename
            
            # Skip .bak backup files
            if filename.endswith('.bak'):
                continue
            
            if is_self_file(file_path):
                self_files.append(file_path)
    
    if not self_files:
        print(f"{YELLOW}No SELF files found in input directory{RESET}")
        return results
    
    print(f"Found {len(self_files)} SELF file(s) to decrypt\n")
    
    # Create output directory structure
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for self_file in self_files:
        relative_path = self_file.relative_to(input_dir)
        
        # Output file keeps same name and extension
        output_file = output_dir / relative_path
        
        # Create parent directories if they don't exist
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"  Decrypting: {relative_path}")
        
        # Decrypt the file
        try:
            success = converter.convert_file(str(self_file), str(output_file))
            
            results['decrypt']['files'][str(self_file)] = {
                'success': success,
                'output': str(output_file),
                'message': 'Success' if success else 'Failed'
            }
            
            if success:
                results['decrypt']['successful'] += 1
                print(f"    {GREEN}✓ Success{RESET}")
            else:
                results['decrypt']['failed'] += 1
                print(f"    {RED}✗ Failed{RESET}")
        except Exception as e:
            results['decrypt']['failed'] += 1
            error_msg = f"Error: {str(e)}"
            results['decrypt']['files'][str(self_file)] = {
                'success': False,
                'output': str(output_file),
                'message': error_msg
            }
            print(f"    {RED}✗ {error_msg}{RESET}")
    
    print(f"\n{CYAN}Decryption complete: {results['decrypt']['successful']} successful, "
          f"{results['decrypt']['failed']} failed{RESET}")
    
    return results

def process_downgrade_and_sign(input_dir: Path, output_dir: Path, sdk_pair: int, 
                               paid: int, ptype: int, create_backup: bool = True,
                               use_colors: bool = True) -> Dict[str, Dict[str, any]]:
    """
    Process files through downgrade and signing pipeline.
    
    Args:
        input_dir: Directory containing decrypted files
        output_dir: Directory for output files
        sdk_pair: SDK version pair number
        paid: Program Authentication ID
        ptype: Program type
        create_backup: Whether to create backups during downgrade
        use_colors: Whether to use colored output
        
    Returns:
        Dictionary with processing results
    """
    results = {
        'downgrade': {'successful': 0, 'failed': 0, 'files': {}},
        'signing': {'successful': 0, 'failed': 0, 'files': {}},
        'fakelib': {'success': False, 'message': ''},
        'librc_patch': {'applied': 0, 'results': {}}
    }
    
    print(f"\n{BLUE}{BOLD}[Step 1/3] Downgrading SDK Versions{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    # Step 1: Downgrade SDK versions
    sdk_patcher = SDKVersionPatcher(
        create_backup=create_backup,
        use_colors=use_colors
    )
    sdk_patcher.set_versions_by_pair(sdk_pair)
    
    ps5_ver, ps4_ver = sdk_patcher.get_current_versions()
    print(f"{CYAN}Using PS5 SDK: 0x{ps5_ver:08X}, PS4 Version: 0x{ps4_ver:08X}{RESET}")
    
    # Find all ELF files in input directory, skipping .bak files
    elf_files = []
    for root, dirs, files in os.walk(input_dir):
        for filename in files:
            file_path = Path(root) / filename
            
            # Skip .bak backup files
            if filename.endswith('.bak'):
                continue
            
            if is_elf_file(file_path):
                elf_files.append(file_path)
    
    if not elf_files:
        print(f"{YELLOW}No ELF files found in input directory {RESET}")
        return results
    
    print(f"Found {len(elf_files)} ELF file(s) to process\n")
    
    for elf_file in elf_files:
        relative_path = elf_file.relative_to(input_dir)
        print(f"  Processing: {relative_path}")
        
        try:
            success, message = sdk_patcher.patch_file(str(elf_file))
            
            results['downgrade']['files'][str(elf_file)] = {
                'success': success,
                'message': message
            }
            
            if success:
                results['downgrade']['successful'] += 1
                print(f"    {GREEN}✓ Success{RESET}")
            else:
                results['downgrade']['failed'] += 1
                print(f"    {RED}✗ {message}{RESET}")
        except Exception as e:
            results['downgrade']['failed'] += 1
            error_msg = f"Error: {str(e)}"
            results['downgrade']['files'][str(elf_file)] = {
                'success': False,
                'message': error_msg
            }
            print(f"    {RED}✗ {error_msg}{RESET}")
    
    print(f"\n{CYAN}Downgrade complete: {results['downgrade']['successful']} successful, "
          f"{results['downgrade']['failed']} failed{RESET}")
    
    # Step 2: Fake sign the downgraded files
    print(f"\n{BLUE}{BOLD}[Step 2/3] Fake Signing Files{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
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
    
    print(f"{CYAN}Using PAID: 0x{paid:016X}, PType: 0x{ptype:08X}{RESET}\n")
    
    for elf_file in elf_files:
        relative_path = elf_file.relative_to(input_dir)
        input_file_str = str(elf_file)
        
        # Skip if downgrade failed
        if not results['downgrade']['files'].get(input_file_str, {}).get('success', False):
            print(f"  Skipping (downgrade failed): {relative_path}")
            results['signing']['files'][str(elf_file)] = {
                'success': False,
                'output': '',
                'message': 'Skipped due to downgrade failure'
            }
            results['signing']['failed'] += 1
            continue
        
        # Output file keeps same name and extension
        output_file = output_dir / relative_path
        
        # Create parent directories if they don't exist
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"  Signing: {relative_path}")
        
        # Sign the file
        try:
            success = converter.sign_file(input_file_str, str(output_file))
            
            results['signing']['files'][str(elf_file)] = {
                'success': success,
                'output': str(output_file),
                'message': 'Success' if success else 'Failed'
            }
            
            if success:
                results['signing']['successful'] += 1
                print(f"    {GREEN}✓ Success{RESET}")
            else:
                results['signing']['failed'] += 1
                print(f"    {RED}✗ Failed{RESET}")
        except Exception as e:
            results['signing']['failed'] += 1
            error_msg = f"Error: {str(e)}"
            results['signing']['files'][str(elf_file)] = {
                'success': False,
                'output': str(output_file),
                'message': error_msg
            }
            print(f"    {RED}✗ {error_msg}{RESET}")
    
    print(f"\n{CYAN}Signing complete: {results['signing']['successful']} successful, "
          f"{results['signing']['failed']} failed{RESET}")
    
    # Step 3: Apply librc.prx patch if SDK pair is 6
    if sdk_pair == 6:
        patched_count, patch_results = apply_librc_patch(output_dir, use_colors)
        results['librc_patch']['applied'] = patched_count
        results['librc_patch']['results'] = patch_results
    
    # Step 4: Copy fakelib directory
    print(f"\n{BLUE}{BOLD}[Step 4/3] Copying Fakelib Directory{RESET}")
    print(f"{YELLOW}{'─' * 60}{RESET}")
    
    # Find project root
    project_root = Path(__file__).parent
    success, message = copy_fakelib(project_root, output_dir)
    
    results['fakelib']['success'] = success
    results['fakelib']['message'] = message
    
    if success:
        print(f"{GREEN}✓ {message}{RESET}")
    else:
        print(f"{YELLOW}⚠ {message}{RESET}")
    
    return results

def process_full_pipeline(input_dir: Path, output_dir: Path, sdk_pair: int, 
                         paid: int, ptype: int, create_backup: bool = True,
                         use_colors: bool = True) -> Dict[str, Dict[str, any]]:
    """
    Process files through full pipeline: decrypt → downgrade → sign.
    
    Args:
        input_dir: Directory containing SELF files
        output_dir: Directory for final output files
        sdk_pair: SDK version pair number
        paid: Program Authentication ID
        ptype: Program type
        create_backup: Whether to create backups during downgrade
        use_colors: Whether to use colored output
        
    Returns:
        Dictionary with processing results
    """
    
    # Create temporary directory for intermediate files
    import tempfile
    temp_dir = Path(tempfile.mkdtemp(prefix="ps5_elf_"))
    
    try:
        print(f"{CYAN}Using temporary directory: {temp_dir}{RESET}")
        
        # Step 1: Decrypt
        decrypt_results = decrypt_files(input_dir, temp_dir, use_colors)
        
        if decrypt_results['decrypt']['successful'] == 0:
            print(f"{RED}No files successfully decrypted. Aborting pipeline.{RESET}")
            return {
                'decrypt': decrypt_results['decrypt'],
                'downgrade': {'successful': 0, 'failed': 0, 'files': {}},
                'signing': {'successful': 0, 'failed': 0, 'files': {}},
                'fakelib': {'success': False, 'message': 'Pipeline aborted'},
                'librc_patch': {'applied': 0, 'results': {}}
            }
        
        # Step 2: Downgrade and sign
        downgrade_sign_results = process_downgrade_and_sign(
            temp_dir, output_dir, sdk_pair, paid, ptype, create_backup, use_colors
        )
        
        # Combine results
        results = {
            'decrypt': decrypt_results['decrypt'],
            'downgrade': downgrade_sign_results['downgrade'],
            'signing': downgrade_sign_results['signing'],
            'fakelib': downgrade_sign_results['fakelib'],
            'librc_patch': downgrade_sign_results['librc_patch']
        }
        
        return results
        
    finally:
        # Clean up temporary directory
        try:
            shutil.rmtree(temp_dir)
            if use_colors:
                print(f"{CYAN}Cleaned up temporary directory{RESET}")
        except:
            pass

def print_summary(results: Dict[str, Dict[str, any]], output_dir: Path, operation: str):
    """Print a summary of the processing results."""
    print(f"\n{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")
    print(f"{CYAN}{BOLD}                      PROCESSING SUMMARY                     {RESET}")
    print(f"{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")
    
    operation_display = {
        'downgrade_and_sign': 'Downgrade & Sign',
        'decrypt_only': 'Decrypt Only',
        'full_pipeline': 'Full Pipeline'
    }
    
    print(f"\n{BOLD}Operation:{RESET} {operation_display.get(operation, operation)}")
    
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
    
    if 'librc_patch' in results:
        patch = results['librc_patch']
        if patch.get('applied', 0) > 0:
            print(f"\n{BOLD}Librc.prx Patch Results:{RESET}")
            print(f"  {GREEN}Files patched: {patch['applied']}{RESET}")
            if patch.get('results'):
                print(f"  {CYAN}Details: {len(patch['results'])} file(s) processed{RESET}")
        elif 'results' in patch and patch['results']:
            print(f"\n{BOLD}Librc.prx Patch Results:{RESET}")
            print(f"  {YELLOW}No files were patched (pattern not found){RESET}")
    
    if 'fakelib' in results:
        fakelib = results['fakelib']
        if fakelib.get('message'):
            print(f"\n{BOLD}Fakelib Copy:{RESET}")
            if fakelib.get('success', False):
                print(f"  {GREEN}✓ {fakelib['message']}{RESET}")
            else:
                print(f"  {YELLOW}⚠ {fakelib['message']}{RESET}")
    
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

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='PS5 ELF Processing Tool - Downgrade, fake sign, and decrypt ELF/SELF files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Interactive mode (will prompt for all options):
    python main.py
  
  Command-line mode:
    python main.py --mode downgrade --input decrypted_files/ --output processed_files/
    python main.py --mode decrypt --input signed_files/ --output decrypted_files/
    python main.py --mode full --input encrypted_files/ --output final_files/
  
  With all options:
    python main.py --mode full --input in/ --output out/ --sdk-pair 4 
                   --paid 0x3100000000000002 --ptype fake --batch --no-backup
        """
    )
    
    # Operation mode argument
    parser.add_argument(
        '--mode', '-m',
        type=str,
        choices=['downgrade', 'decrypt', 'full'],
        help='Operation mode: downgrade (ELF to SELF), decrypt (SELF to ELF), full (both)'
    )
    
    # Input/output arguments (not required for interactive mode)
    parser.add_argument(
        '--input', '-i',
        type=str,
        help='Input directory containing files'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='Output directory for processed files'
    )
    
    # Downgrade-specific arguments
    parser.add_argument(
        '--sdk-pair', '-s',
        type=int,
        help='SDK version pair number (1-10, for downgrade/full modes)'
    )
    
    parser.add_argument(
        '--paid',
        type=str,
        help='Program Authentication ID (hex, e.g., 0x3100000000000002)'
    )
    
    parser.add_argument(
        '--ptype',
        type=str,
        help='Program type (name or hex, e.g., "fake" or "0x1")'
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
        '--batch',
        action='store_true',
        help='Run in batch mode without interactive prompts'
    )
    
    args = parser.parse_args()
    
    # Print banner
    print_banner()
    
    # Check if we're in interactive mode (no arguments provided)
    is_interactive = not any([
        args.mode, args.input, args.output, args.sdk_pair, 
        args.paid, args.ptype, args.no_backup, args.batch
    ])
    
    # Get operation mode
    if args.mode:
        operation_map = {
            'downgrade': 'downgrade_and_sign',
            'decrypt': 'decrypt_only',
            'full': 'full_pipeline'
        }
        operation = operation_map[args.mode]
    elif is_interactive or not args.batch:
        operation = get_operation_choice()
    else:
        operation = 'downgrade_and_sign'  # Default in batch mode
    
    # Get input directory
    if args.input:
        input_dir = Path(args.input)
    elif is_interactive or not args.batch:
        input_path = input(f"{CYAN}Enter input directory: {RESET}").strip()
        if not input_path:
            print(f"{RED}Error: Input directory is required{RESET}")
            sys.exit(1)
        input_dir = Path(input_path)
    else:
        print(f"{RED}Error: Input directory required in batch mode{RESET}")
        parser.print_help()
        sys.exit(1)
    
    # Validate input directory
    if not input_dir.exists():
        print(f"{RED}Error: Input directory does not exist: {input_dir}{RESET}")
        sys.exit(1)
    
    if not input_dir.is_dir():
        print(f"{RED}Error: Input path is not a directory: {input_dir}{RESET}")
        sys.exit(1)
    
    # Get output directory
    if args.output:
        output_dir = Path(args.output)
    elif is_interactive or not args.batch:
        output_path = input(f"{CYAN}Enter output directory: {RESET}").strip()
        if not output_path:
            print(f"{RED}Error: Output directory is required{RESET}")
            sys.exit(1)
        output_dir = Path(output_path)
    else:
        print(f"{RED}Error: Output directory required in batch mode{RESET}")
        parser.print_help()
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get configuration based on operation mode
    sdk_pair = None
    paid = None
    ptype = None
    
    if operation in ['downgrade_and_sign', 'full_pipeline']:
        # Get SDK version pair
        sdk_pairs = SDKVersionPatcher.get_supported_pairs()
        
        if args.sdk_pair:
            sdk_pair = args.sdk_pair
            if sdk_pair not in sdk_pairs:
                print(f"{RED}Error: Invalid SDK pair. Must be between 1 and {len(sdk_pairs)}{RESET}")
                sys.exit(1)
        elif is_interactive or not args.batch:
            sdk_pair = get_sdk_version_choice()
        else:
            sdk_pair = 4  # Default in batch mode
        
        # Get PAID
        if args.paid:
            try:
                if args.paid.startswith('0x'):
                    paid = int(args.paid, 16)
                else:
                    paid = int(args.paid, 0)
                
                if not (0 <= paid <= 0xFFFFFFFFFFFFFFFF):
                    print(f"{RED}Error: PAID must be a 64-bit value (0-0xFFFFFFFFFFFFFFFF){RESET}")
                    sys.exit(1)
            except ValueError:
                print(f"{RED}Error: Invalid PAID format. Use hex (0x...) or decimal{RESET}")
                sys.exit(1)
        elif is_interactive or not args.batch:
            paid = get_paid_choice()
        else:
            paid = 0x3100000000000002  # Default in batch mode
        
        # Get PType
        if args.ptype:
            try:
                if args.ptype.startswith('0x'):
                    ptype = int(args.ptype, 16)
                else:
                    try:
                        ptype = int(args.ptype, 0)
                    except ValueError:
                        ptype = FakeSignedELFConverter.parse_ptype(args.ptype.lower())
                
                if not (0 <= ptype <= 0xFFFFFFFF):
                    print(f"{RED}Error: PType must be a 32-bit value (0-0xFFFFFFFF){RESET}")
                    sys.exit(1)
            except Exception as e:
                print(f"{RED}Error: Invalid ptype '{args.ptype}': {str(e)}{RESET}")
                print(f"Valid options: fake, npdrm_exec, npdrm_dynlib, system_exec, system_dynlib, host_kernel, secure_module, secure_kernel")
                sys.exit(1)
        elif is_interactive or not args.batch:
            ptype = get_ptype_choice()
        else:
            ptype = 1  # Default in batch mode
    
    # Print configuration
    print(f"\n{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")
    print(f"{CYAN}{BOLD}                      CONFIGURATION                         {RESET}")
    print(f"{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")
    print(f"  {BOLD}Operation:{RESET} {operation.replace('_', ' ').title()}")
    print(f"  {BOLD}Input Directory:{RESET} {input_dir}")
    print(f"  {BOLD}Output Directory:{RESET} {output_dir}")
    
    if operation in ['downgrade_and_sign', 'full_pipeline']:
        ps5_sdk_version, ps4_version = sdk_pairs[sdk_pair]
        print(f"  {BOLD}SDK Version Pair:{RESET} {sdk_pair} (PS5: 0x{ps5_sdk_version:08X}, PS4: 0x{ps4_version:08X})")
        print(f"  {BOLD}PAID:{RESET} 0x{paid:016X}")
        print(f"  {BOLD}PType:{RESET} 0x{ptype:08X}")
        print(f"  {BOLD}Create Backup:{RESET} {'Yes' if not args.no_backup else 'No'}")
        
        # Special note for SDK pair 6
        if sdk_pair == 6:
            print(f"  {YELLOW}{BOLD}Note:{RESET} SDK pair 6 selected - will apply librc.prx patch after signing{RESET}")
    
    print(f"{BLUE}{BOLD}══════════════════════════════════════════════════════════{RESET}")
    
    # Confirm before proceeding
    if is_interactive or not args.batch:
        confirm = input(f"\n{CYAN}Proceed with processing? (y/N): {RESET}").strip().lower()
        if confirm not in ['y', 'yes']:
            print(f"{YELLOW}Processing cancelled.{RESET}")
            sys.exit(0)
    
    # Process files based on operation
    try:
        if operation == 'decrypt_only':
            results = decrypt_files(
                input_dir=input_dir,
                output_dir=output_dir,
                use_colors=not args.no_colors
            )
        
        elif operation == 'downgrade_and_sign':
            results = process_downgrade_and_sign(
                input_dir=input_dir,
                output_dir=output_dir,
                sdk_pair=sdk_pair,
                paid=paid,
                ptype=ptype,
                create_backup=not args.no_backup,
                use_colors=not args.no_colors
            )
        
        elif operation == 'full_pipeline':
            results = process_full_pipeline(
                input_dir=input_dir,
                output_dir=output_dir,
                sdk_pair=sdk_pair,
                paid=paid,
                ptype=ptype,
                create_backup=not args.no_backup,
                use_colors=not args.no_colors
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

if __name__ == "__main__":
    main()