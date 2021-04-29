# TwitchMarkov
A Markov chain generator for Twitch.

### Setup
- Install dependencies
> pip install -r requirements.txt
- Make a Twitch Account
- [Register Twitch Application](https://dev.twitch.tv/console/apps)
- Add the twitchAPI OAuth Redirect URL of http://localhost:17563 in the [Twitch Developer Console](https://dev.twitch.tv/console/apps). If you will be using the application in a cli only environment, you also need to add https://retrohollow.com/twitchAuth.php
- Fill out the config.yaml file.
- Execute.
> python twitchMarkov.py

### Config
You need to set up your config file before you run the program.

* **twitch**:
  * **client_id**: The client ID of your registered Twitch application to interface with the Twitch API. This is received from the [Twitch Developer Portal](https://dev.twitch.tv/console/apps).
  * **client_secret**: The client secret of your registered Twitch application to interface with the Twitch API. This is received from the [Twitch Developer Portal](https://dev.twitch.tv/console/apps).
  * **username**: The display name of the Twitch account that the bot will use.
  * **channels**:
    * **Some_Channel_Name**: The name of a Twitch Channel to join.
      * **ignored_users**: List of users the bot will ignore.
      * **clear_logs_after**: (True/False) Whether or not to clear logs after
      * **unique**: (True/False) Whether you want to generate unique phrases.
      * **generate_on**: The number of messages after which the bot will generate a message.
  * **irc**:
    * **server**: The server the IRC bot will connect to. Do not change!
    * **port**: The server the IRC bot will connect to. Do not change!
* **markov**:
  * **percent_unique**: The percent uniqueness to compare to for qualifying a unique phrase.
  * **allow_mentions**: Allow mentions in messages.
  * **state_size**: Markov chain state size
  * **times_to_try**: How many times the Markov Chain will attempt to generate a proper sentence
  * **cull_over**: How many lines to cull to
  * **time_to_cull**: How many seconds to trigger culling
  * **blacklist_file**: File with blacklisted words
  * **defaults**: The default settings for channel specific options
    * **ignored_users**: List of users the bot will ignore.
    * **clear_logs_after**: (True/False) Whether or not to clear logs after
    * **unique**: (True/False) Whether you want to generate unique phrases.
    * **generate_on**: The number of messages after which the bot will generate a message.
