from markovHandler import markovHandler
import retroBot
from threading import Thread
from time import sleep
import re
import logging
import logging.handlers
import os

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
        self.irc_server = config['twitch']['irc']['server']
        self.irc_port = config['twitch']['irc']['port']
        for channel in config['twitch']['channels']:
            channel_config = config['twitch']['channels'][channel]
            for setting in config['markov']['defaults']:
                if not setting in channel_config or not channel_config[setting]:
                    channel_config[setting] = config['markov']['defaults'][setting]
            self.config.save()
        super(markovBot, self).__init__(config['twitch']['username'], config['twitch']['client_id'], config['twitch']['client_secret'], config['twitch']['channels'], handler=markovHandler)
        
    def load_blacklist(self, blacklist_file):
        with open(blacklist_file, 'r') as f:
            words = [line.rstrip('\n') for line in f]
        return words

    def checkBlacklisted(self, message):
        # Check words that the bot should NEVER learn.
        for i in self.blacklist_words:
            if re.search(r"\b" + i, message, re.IGNORECASE):
                return True
        return False


def main():
    logger = setup_logger('markovBot')
    config = load_config(os.path.join(os.path.dirname(__file__), 'config.yaml'))
    bot = markovBot(config)
    bot.start()

def load_config(filename):
    config = markovConfig(filename)
    config.save()
    return config

def setup_logger(logname, logpath=""):
    if not logpath or logpath == "":
        logpath = os.path.join(os.path.dirname(__file__), 'logs')
    else:
        logpath = os.path.abspath(logpath)
    if not os.path.exists(logpath):
        os.mkdir(logpath)
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