One day I found RustAdmin for Desktop was not working for me, and I realized if the dev ever pulled the plug on the free version and went completely cloud based, I would be SOL. Because of thta, I decided to make a simple Python script that is very bare bones, but does the same thing.



###### Features:

* One-window GUI (Tkinter) with resizable tabs: Console and Players. 
* Live console with colored tags (e.g., \[OK], \[ERROR], \[INFO], \[Chat]) and automatic log file output. 
* Players tab: auto-parses status output into a table (Name, Ping, SteamID, Connected), with type-to-filter search and click-to-sort headers. 
* Quick commands: hit Enter to send, and the app also auto-polls status at intervals to keep the player list fresh. 
* Config + Logs saved to Documents (RAT\_config.JSON, RAT\_log.JSON) so your connection details and console history persist. 
* Threaded + asyncio architecture keeps the UI responsive while the WebSocket runs in the background. 



###### Requires:

Python 3.8+ (Tkinter included on most Python builds)

pip packages

