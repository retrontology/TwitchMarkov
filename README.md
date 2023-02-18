# TwitchMarkov

## Description
This is fork of [metalgearsvt](https://github.com/metalgearsvt)'s Twitch Markov bot [TwitchMarkov](https://github.com/metalgearsvt/TwitchMarkov). I've refactored it to use my Twitch bot package [retroBot](https://github.com/retrontology/retroBot). This allows for one instance to work in multiple, separate channels while only running one instance. It has also be updated to use sqlite as the message DB instead of storing them as a plain text file.

## Setup
### Install dependencies
Simply install the dependencies located in the [requirement.txt](https://github.com/retrontology/TwitchMarkov/blob/main/requirements.txt) file:
```
python3 -m pip install -r requirements.txt
```

### Config file
You will also need to populate the yaml configuration file with the proper values for your bot:

>`config.yaml`
```
twitch:
  client_id: 'The client ID of your Twitch application'
  client_secret: 'The client secret of your Twitch application'
  username: 'The username of the bot'
  channels:
    'The name of a Twitch channel to join':
      ignored_users:
        - 'I would recommend'
        - 'adding bot accounts'
        - 'in this section'
      clear_logs_after: Whether to clear message logs for this channel after posting a message (True/False)
      send_messages: Whether to send messages in this channel (True/False)
      unique: Whether to only post messages that are unique from previously posted messages (True/False)
      generate_on: The amount of messages that will trigger the bot to post. AKA the interval (Positive Integer)
  irc:
    server: 'irc.chat.twitch.tv'
    port: 6667
markov:
  percent_unique: Threshold percentage for uniqueness (Float)
  allow_mentions: Whether to allow mentions in the bot's messages or not (True/False)
  state_size: The state size for the Markov chains (Positive Integer)
  times_to_try: How many times to try to make a sentence(Positive Integer)
  cull_over: The maximum amount of messages you want to retain for each channel (Positive Integer)
  time_to_cull: How often the bot checks if it needs to cull the messages for each channel (Positive Integer)
  blacklist_file: 'The text file with line separated blacklisted words'
  defaults:
    ignored_users:
        - 'I would recommend'
        - 'adding bot accounts'
        - 'in this section'
    clear_logs_after:  Whether to clear message logs after posting a message by default (True/False)
    send_messages: Whether to send messages by default (True/False)
    unique: Whether to only post messages that are unique from previously posted messages by default (True/False)
    generate_on: The amount of messages that will trigger the bot to post. AKA the interval (Positive Integer)
```

## Run
To run the bot you simply need to run the following file with python (after the setup steps above have been completed):
```
python3 TwitchMarkov.py
```