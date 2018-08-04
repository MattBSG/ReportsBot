# Discord reporting bot for Minecraft players
This project was originally designed for the WarzoneMC server and is, for the most part, not going to be compatible elsewhere. **I will not provide support for this project. If you find a legitimate bug, open an issue and I __may__ fix it eventually**

Some simple setup is required, here's what you'll need:
* An up-to-date mongodb server
* Python3.5+
* 24/7 hosting (is designed with certain aspects on running constantly)
* A good attitude


First step is to clone and install pip dependencies with pip: `pip install -U -r requirements.txt` in the directory you cloned the repository. Then make two collections called `cases` and `appeals` in a new database called `reports`. Now edit the necessary values in `constants.py` and after which you will be able to run the bot with `python3 bot.py` (replacing 3 with your system's version if required.)
