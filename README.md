# webircbot
An IRC bot that lets users browse the modern web, follow links and create and search presonnal pages crated by other users.

## Setup
**Note: on Windows, it is recommended to use cmd.exe instead of PowerShell.**
- Make sure you have enough space to store all user data.
- Download webirc.py
- Go to the bottom of webirc.py and change server, port and nickname.
- Run ```pip install irc requests bs4``` to install the libraries needed to run this bot. You may need to create a virtualenv with ```python3 -m venv webirc-venv; source webirc-venv/bin/activate``` on UNIX like systems or ```py -m venv webirc-venv; webirc-venv\Scripts\activate``` on Windows.
- Run ```python3 webirc.py``` on UNIX like systems, or ```py webirc.py``` on Windows.

## License
See LICENSE.
