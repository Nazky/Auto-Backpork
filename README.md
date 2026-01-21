# Auto-Backpork
A project to make backport for the PS5 using backpork easy and fast.

---

## F.A.Q

### What is this ?
This is a project that allow you to downgrade, fake signed and add fakelib to you'r ps5 games easily.

### Why using this ?
This project work using directories, simply put a input directory (decrypted game files), and a ouput directory, everything else is done automaticlly.

### Where can i find the decrypted games files and the fakelib files ?
For legals reasons (and because i don't want my github account banned lol) i can't help with that here.

---

## How to use

- Make sure to have [Python](https://www.python.org/downloads/) installed.
- Put you'r patched and signed sprx files inside the folder **"fakelib"**.
- Once you have [Python](https://www.python.org/downloads/) run 
```bash
 python main.py
```
- You can choose between 3 mode : downgrade, decrypt or full, if you don't have the decrypted files of your games you can choose the full option otherwise choose downgrade (default one).
- For the first option (input directory) put the directory of you'r game files.
- For the second option (output directory) put the directory where you'r downgraded and signed game files should be save.
- If you don't know what the others options are doing keep the default value.
- When you are sure of you'r configuration simply type "y" to confirme.
- When it's done you should have all the game files downgraded and signed with the fakelib folder, you can now copy and replace you'r old game files (make sure fakelib is in the root of the game folder).
- Make sure to run the Backpork payload for every new games (you maybe have to run [chmod_rec](https://github.com/zecoxao/chmod_rec) too).

### One line command
You can also run a one line command, for exemple to simply downgrade to 7.00 and sign your game:
```bash
 python main.py --input "/home/user/ps5/decrypted" --output "/home/user/ps5/signed" --sdk-pair 7 --batch
```
Or if you want to also decrypt the fake sign ELF:
```bash
 python main.py --mode full --input "/home/user/ps5/encrypted" --output "/home/user/ps5/signed" --sdk-pair 7 --batch
```

## TODO
- [X] Add FSELF decryptor.
- [ ] Add BPS files patcher.

## Credit
[idlesauce](https://github.com/idlesauce) | [ps5_elf_sdk_downgrade.py ](https://gist.github.com/idlesauce/2ded24b7b5ff296f21792a8202542aaa)

[john-tornblom](https://github.com/john-tornblom) | [make_fself.py](https://github.com/ps5-payload-dev/sdk/blob/master/samples/install_app/make_fself.py)

[BestPig](https://github.com/BestPig) | [BackPork](https://github.com/BestPig/BackPork)

[zecoxao](https://github.com/zecoxao) | [chmod_rec](https://github.com/zecoxao/chmod_rec)

[EchoStretch](https://github.com/EchoStretch) |[PS5-app-dumper](https://github.com/EchoStretch/ps5-app-dumper)
