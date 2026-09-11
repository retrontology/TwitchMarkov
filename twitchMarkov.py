from markovHandler import markovHandler
import retroBot
from retroBot.config import config as markovConfig
from appdirs import user_data_dir
from paths import get_config_file, get_logs_dir, resolve_data_path
import re
import logging
import logging.handlers
import os
import sys

class markovBot(retroBot.retroBot):

    def __init__(self, config):
        self.config = config
        self.percent_unique = config['markov']['percent_unique']
        self.allow_mentions = config['markov']['allow_mentions']
        self.state_size = config['markov']['state_size']
        self.times_to_try = config['markov']['times_to_try']
        self.cull_over = config['markov']['cull_over']
        self.time_to_cull = config['markov']['time_to_cull']
        self.blacklist_file = config['markov']['blacklist_file']
        self.blacklist_words = self.load_blacklist(self.blacklist_file)
        self.username = config['twitch']['username']
        self.client_id = config['twitch']['client_id']
        self.client_secret = config['twitch']['client_secret']
        for channel in config['twitch']['channels']:
            channel_config = config['twitch']['channels'][channel]
            for setting in config['markov']['defaults']:
                if not setting in channel_config or not channel_config[setting]:
                    channel_config[setting] = config['markov']['defaults'][setting]
            self.config.save()
        super(markovBot, self).__init__(config['twitch']['username'], config['twitch']['client_id'], config['twitch']['client_secret'], config['twitch']['channels'], handler=markovHandler)
        
    def load_blacklist(self, blacklist_file):
        # An unset blacklist is valid: the shipped config leaves it empty.
        if not blacklist_file:
            return []
        blacklist_file = resolve_data_path(blacklist_file)
        if not os.path.isfile(blacklist_file):
            logging.getLogger('retroBot').warning(f'Blacklist file not found, continuing without one: {blacklist_file}')
            return []
        with open(blacklist_file, 'r') as f:
            # Strip blanks and # comments: an empty entry compiles to \b, which matches
            # every message and would silently blacklist all of chat.
            return [w for line in f if (w := line.strip()) and not w.startswith('#')]

    def checkBlacklisted(self, message):
        # Check words that the bot should NEVER learn.
        for i in self.blacklist_words:
            if re.search(r"\b" + i, message, re.IGNORECASE):
                return True
        return False


def check_oauth(username):
    # retroBot stores its token pickle under appdirs; mirror that path so we can fail
    # fast instead of blocking on the interactive input() inside userAuth.
    token_file = os.path.join(user_data_dir('retroBot', 'retrontology'), f'{username}_oauth.pickle')
    if os.path.exists(token_file) or sys.stdin.isatty():
        return
    logger = logging.getLogger('retroBot')
    logger.error(f'No Twitch OAuth token found at {token_file} and no terminal is attached to authorize one.')
    logger.error('Run the one-time interactive authorization first: docker compose run --rm -it twitchmarkov')
    sys.exit(1)

def main():
    logger = setup_logger('retroBot')
    config_file = get_config_file()
    if not os.path.isfile(config_file):
        logger.error(f'Config file not found: {config_file}')
        sys.exit(1)
    config = load_config(config_file)
    check_oauth(config['twitch']['username'])
    bot = markovBot(config)
    bot.start()

def load_config(filename):
    config = markovConfig(filename)
    config.save()
    return config

def setup_logger(logname, logpath=""):
    if not logpath or logpath == "":
        logpath = get_logs_dir()
    else:
        logpath = os.path.abspath(logpath)
        os.makedirs(logpath, exist_ok=True)
    logger = logging.getLogger(logname)
    logger.setLevel(logging.DEBUG)
    file_handler = logging.handlers.TimedRotatingFileHandler(os.path.join(logpath, logname), when='midnight')
    stream_handler = logging.StreamHandler()
    form = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    file_handler.setFormatter(form)
    stream_handler.setFormatter(form)
    file_handler.setLevel(logging.INFO)
    stream_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger

if __name__ == '__main__':
    main()
