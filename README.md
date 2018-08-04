# Discord reporting bot for Minecraft players
This project was originally designed for the WarzoneMC server and is, for the most part, not going to be compatible elsewhere. **I will not provide support for this project. If you find a legitimate bug, open an issue and I __may__ fix it eventually**

Some simple setup is required, here's what you'll need:
* An up-to-date mongodb server
* Python3.5+
* 24/7 hosting (is designed with certain aspects on running constantly)
* A good attitude

Start off by making two collections called `cases` and `appeals` in a new database called `reports`. You can clone the repository and edit the necessary values in `constants.py` after which you will be able to run the bot with `python3 bot.py` and replacing 3 with your system's version if required.
