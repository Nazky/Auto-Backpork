# Auto-BackPork
A project to make backport for the PS5 using [BackPork](https://github.com/BestPig/BackPork) easy and fast.

---

## F.A.Q

### What is this ?
This is a project that allow you to downgrade, fake signed and add fakelib to your ps5 games easily.

### Why using this ?
This project work using directories, simply put a input directory and a ouput directory, everything else is done automatically.

### Where can i find the fakelib files ?
For legals reasons (and because i don't want my github account banned lol) i can't help with that here.

---

## How to use

### CLI
- Make sure to have [Python 3.7+](https://www.python.org/downloads/) installed.
- Put your patched and signed sprx files inside the folder **"fakelib"**.
- Once you have [Python 3.7+](https://www.python.org/downloads/) run 
```bash
python Backport.py
```
- You can choose between 4 mode : Auto (default), Downgrade, Decrypt or Legacy pipeline (for backward compatibility).
- For the first option (input directory) put the directory of your game files.
- For the second option (output directory) put the directory where your downgraded and signed game files should be save.
- If you don't know what the others options are doing keep the default value.
- When you are sure of you're configuration simply type "y" to confirme.
- When it's done you should have all the game files downgraded and signed with the fakelib folder, you can now copy and replace your old game files (make sure fakelib is in the root of the game folder).
- Make sure to run the [BackPork](https://github.com/BestPig/BackPork) payload (you maybe have to run [chmod_rec](https://github.com/zecoxao/chmod_rec) too).

### One line command
You can also run a one line command, for exemple to simply downgrade to 7.00:
```bash
python Backport.py --input "/home/user/ps5/decrypted" --output "/home/user/ps5/signed" --sdk-pair 7
```
Or if you want to only decrypt the fake sign ELF:
```bash
python Backport.py --mode decrypt --input "/home/user/ps5/encrypted" --output "/home/user/ps5/decrypted"
```
You can also directly use archive files as input, the tool automatically detects and extracts:
```bash
# Extract and process a ZIP file
python Backport.py --input game_files.zip --output output/ --sdk-pair 4

# Extract and process a RAR archive with password (not ready yet)
python Backport.py --input game.part1.rar --output output/ --password "mypassword"

# Extract and process a 7z archive
python Backport.py --input game.7z --output output/ --sdk-pair 4

# Multi-part archive support (provide the first part | not ready yet)
python Backport.py --input game.7z.001 --output output/
```

---

## GUI
You can also use the graphical interface (in beta for now but should work fine, expect some bugs), you can either download the latest release [here](https://github.com/Nazky/Auto-Backpork/releases) or use the run script for your os, when the gui start make sure to go to the settings to add your fakelib folder to be able to backport (work with archive files too).

### Windows
1. Make sure to have [Python 3.7+](https://www.python.org/downloads/) installed if you want to use the run.bat.
2. If you want to enable support for rar and 7z files you need to install [7-zip](https://www.7-zip.org/) and [WinRAR](https://www.win-rar.com/), if you use the "run.bat" 7-zip should install automatically but you still need to install [WinRAR](https://www.win-rar.com/) manually.
3. Run the gui by either downloading the latest release or by using the run.bat.

### Linux/MacOS
1. Make sure to have [Python 3.7+](https://www.python.org/downloads/) installed if you want to use the run.sh.
2. If you want to enable support for rar and 7z files you need to install [7-zip](https://www.7-zip.org/) and [unrar](https://www.rarlab.com/rar_add.htm), if you use the "run.sh" both should install automatically, if you running the Appimage or the Mac App install both using your package management.

#### Linux
Debian/Ubuntu :
sudo apt install p7zip-full unrar

Fedora :
sudo dnf install p7zip p7zip-plugins unrar

Arch :
sudo pacman p7zip unrar

#### MacOS :
Make sure you have [Homebrew](https://brew.sh/) installed first.
brew install p7zip rar

---

## Python library
You can also use this project as a Python library, you only need the "Backport.py" and "src" folder. 

For exemple to use the full pipeline:
```python
from Backport import PS5ELFProcessor
from pathlib import Path

def process_game_package():
    """Process a PS5 game using the backport library."""
    
    # Initialize processor
    processor = PS5ELFProcessor(use_colors=True)
    
    # Define paths
    input_dir = Path("C:/PS5/MyGame/encrypted")
    output_dir = Path("C:/PS5/MyGame/backported")
    
    # Get default SDK pair info
    sdk_pairs = processor.get_supported_sdk_pairs()
    print(f"Available SDK pairs: {sdk_pairs}")
    
    # Use SDK pair 7 (commonly used for backports)
    sdk_pair = 7
    paid = 0x3100000000000002  # Fake PAID
    ptype = 1  # Fake program type
    
    # Run the full processing pipeline
    results = processor.decrypt_and_sign_pipeline(
        input_dir=input_dir,
        output_dir=output_dir,
        sdk_pair=sdk_pair,
        paid=paid,
        ptype=ptype,
        fakelib_source=None,  # Optional fakelib directory
        create_backup=True,
        overwrite=False,
        apply_libc_patch=True,
        auto_revert_for_high_sdk=True,
        verbose=True
    )
    
    # Analyze results
    print(f"\nProcessing Summary:")
    print(f"  Decrypted: {results.get('decrypt', {}).get('successful', 0)}")
    print(f"  Downgraded: {results.get('downgrade', {}).get('successful', 0)}")
    print(f"  Signed: {results.get('signing', {}).get('successful', 0)}")
    
    return results

if __name__ == "__main__":
    results = process_game_package()
```

Or if you only want to work with one file:
```python
from Backport import decrypt_file, sign_file, get_sdk_version_info

def process_single_files():
    """Process individual files using convenience functions."""
    
    # Get SDK version info
    sdk_pairs = get_sdk_version_info()
    print(f"SDK Pair 7: PS5 SDK = 0x{sdk_pairs[7][0]:08X}")
    
    # Decrypt a single SELF file
    decrypt_success = decrypt_file(
        input_file="/path/to/eboot.self",
        output_file="/path/to/eboot.elf",
        verbose=True
    )
    
    if decrypt_success:
        print("File decrypted successfully!")
        
        # Sign the decrypted ELF file
        sign_success = sign_file(
            input_file="/path/to/eboot.elf",
            output_file="/path/to/eboot_fakesigned.self",
            sdk_pair=7,
            paid=0x3100000000000002,
            ptype=1,
            verbose=True
        )
        
        if sign_success:
            print("File signed successfully!")
```

You can also process archive files directly using the library:

```python
from Backport import PS5ELFProcessor
from src.Archive import ArchiveHandler, extract_archive_to_temp, cleanup_temp_dir
from pathlib import Path

def process_archive():
    """Process an archive file directly."""
    
    # Initialize processor
    processor = PS5ELFProcessor(use_colors=True)
    
    # Archive file path
    archive_path = Path("/path/to/game.7z")
    
    # Extract archive to temporary directory
    temp_dir, result = extract_archive_to_temp(
        archive_path=archive_path,
        verbose=True,
        provided_password="optional_password"
    )
    
    if temp_dir is None:
        print("Failed to extract archive")
        return None
    
    try:
        # Process the extracted files
        results = processor.decrypt_and_sign_pipeline(
            input_dir=temp_dir,
            output_dir=Path("/path/to/output"),
            sdk_pair=7,
            paid=0x3100000000000002,
            ptype=1,
            verbose=True
        )
        
        return results
        
    finally:
        # Clean up temporary directory
        cleanup_temp_dir(temp_dir, verbose=True)
```

---

## TODO
- [X] Add FSELF decryptor.
- [X] Add support for fw =<7.
- [ ] Add BPS files patcher.
- [X] Add a GUI.
- [ ] Add/Fix support for password protected archives.
- [ ] Add/Fix support for multipart archvies.
- [ ] Clean the code.

## Credit
[idlesauce](https://github.com/idlesauce) | [ps5_elf_sdk_downgrade.py ](https://gist.github.com/idlesauce/2ded24b7b5ff296f21792a8202542aaa)

[john-tornblom](https://github.com/john-tornblom) | [make_fself.py](https://github.com/ps5-payload-dev/sdk/blob/master/samples/install_app/make_fself.py)

[BestPig](https://github.com/BestPig) | [BackPork](https://github.com/BestPig/BackPork)

[zecoxao](https://github.com/zecoxao) | [chmod_rec](https://github.com/zecoxao/chmod_rec)

[EchoStretch](https://github.com/EchoStretch) |[PS5-app-dumper](https://github.com/EchoStretch/ps5-app-dumper)
