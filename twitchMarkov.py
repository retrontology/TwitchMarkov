from markovConfig import markovConfig
from channelHandler import channelHandler
from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.types import AuthScope
from emoji import demojize
import datetime
import socket
import markovify
import re
import traceback
import irc.bot
import logging
import pickle
import os


class markovBot(irc.bot.SingleServerIRCBot):

    def __init__(self, config):
        self.logger = logging.getLogger("markovBot.bot")
        self.percent_unique = config['markov']['percent_unique']
        self.allow_mentions = config['markov']['allow_mentions']
        self.phrases_list = config['markov']['phrases_list']
        self.state_size = config['markov']['state_size']
        self.clear_logs_after = config['markov']['clear_logs_after']
        self.send_messages = config['markov']['send_messages']
        self.generate_on = config['markov']['generate_on']
        self.times_to_try = config['markov']['times_to_try']
        self.unique = config['markov']['unique']
        self.cull_over = config['markov']['cull_over']
        self.time_to_cull = config['markov']['time_to_cull']
        self.blacklist_file = config['markov']['blacklist_file']
        self.blacklist_words = self.load_blacklist(self.blacklist_file)
        self.username = config['twitch']['username']
        self.client_id = config['twitch']['client_id']
        self.client_secret = config['twitch']['client_secret']
        self.twitch_setup()
        self.irc_server = config['twitch']['irc']['server']
        self.irc_port = config['twitch']['irc']['port']
        self.channel_handlers = []
        for channel in config['twitch']['channels']:
            self.channel_handlers.append(channelHandler(channel, config['twitch']['channels'][channel].lower(), self))
        irc.bot.SingleServerIRCBot.__init__(self, [(self.irc_server, self.irc_port, 'oauth:'+self.token)], self.username, self.username)

    def on_welcome(self, c, e):
        c.cap('REQ', ':twitch.tv/membership')
        c.cap('REQ', ':twitch.tv/tags')
        c.cap('REQ', ':twitch.tv/commands')
        for channel in self.channel_handlers:
            c.join('#' + channel.channel)

    def on_join(self, c, e):
        self.logger.info(f'Joined {e.target}!')

    def on_pubmsg(self, c, e):
        self.channel_handlers[e.target[1:]].on_pubmsg(c, e)

    
    def load_blacklist(self, blacklist_file):
        with open(blacklist_file, 'r') as f:
            words = [line.rstrip('\n') for line in f]
        return words
    
    def twitch_setup(self):
        self.logger.info(f'Setting up Twitch API client...')
        self.twitch = Twitch(self.client_id, self.client_secret)
        self.twitch.user_auth_refresh_callback = self.oauth_user_refresh
        self.twitch.authenticate_app([])
        self.logger.info(f'Twitch API client set up!')

    def get_oauth_token(self):
        tokens = self.load_oauth_token()
        target_scope = [AuthScope.CHAT_EDIT, AuthScope.CHAT_READ]
        if tokens == None:
            auth = UserAuthenticator(self.twitch, target_scope, force_verify=False)
            self.token, self.refresh_token = auth.authenticate()
            self.save_oauth_token()
        else:
            self.token = tokens[0]
            self.refresh_token = tokens[1]
        self.twitch.set_user_authentication(self.token, target_scope, self.refresh_token)

    def save_oauth_token(self):
        pickle_file = self.get_oauth_file()
        with open(pickle_file, 'wb') as f:
            pickle.dump((self.token, self.refresh_token), f)
        self.logger.debug(f'OAuth Token has been saved')

    def load_oauth_token(self):
        pickle_file = self.get_oauth_file()
        if os.path.exists(pickle_file):
            with open(pickle_file, 'rb') as f:
                out = pickle.load(f)
            self.logger.debug(f'OAuth Token has been loaded')
            return out
        else: return None

    def get_oauth_file(self):
        pickle_dir = os.path.join(os.path.dirname(__file__), 'oauth')
        if not os.path.exists(pickle_dir): os.mkdir(pickle_dir)
        pickle = os.path.join(pickle_dir, f'{self.username}_oauth.pickle')
        return pickle
    
    def oauth_user_refresh(self, token, refresh_token):
        self.logger.debug(f'Refreshing OAuth Token')
        self.token = token
        self.refresh_token = refresh_token
        irc.bot.SingleServerIRCBot.__init__(self, [(self.irc_server, self.irc_port, 'oauth:'+self.token)], self.username, self.username)
        self._connect()
        self.save_oauth_token()

    def listMeetsThresholdToSave(self, part, whole):
        pF = float(len(part))
        wF = float(len(whole))
        if wF == 0:
            return False
        uniqueness = (pF/wF) * float(100)
        return (uniqueness >= self.percent_unique)

    def checkBlacklisted(self, message):
        # Check words that the bot should NEVER learn.
        for i in self.blacklist_words:
            if re.search(r"\b" + i, message, re.IGNORECASE):
                return True
        return False


def old_main():
    # PROGRAM HERE

    last_cull = datetime.datetime.now()

    while True:
        # Initialize socket.
        sock = socket.socket()

        # Connect to the Twitch IRC chat socket.
        sock.connect((Conf.server, Conf.port))

        # Authenticate with the server.
        sock.send(f"PASS {Conf.token}\n".encode('utf-8'))
        sock.send(f"NICK {Conf.nickname}\n".encode('utf-8'))
        sock.send(f"JOIN #{Conf.channel}\n".encode('utf-8'))

        logfile = Conf.channel + "Logs.txt"

        print("Connected", Conf.nickname, ".")

        # Main loop
        while True:
            try:
                # Receive socket message.
                resp = sock.recv(2048).decode('utf-8')

                # Keepalive code.
                if resp.startswith('PING'):
                    sock.send("PONG\n".encode('utf-8'))
                # Actual message that isn't empty.
                elif len(resp) > 0:
                    try:
                        msg = demojize(resp)
                        # Break out username / channel / message.
                        regex = re.search(r':(.*)\!.*@.*\.tmi\.twitch\.tv PRIVMSG #(.*) :(.*)', msg)
                        # If we have a matching message, do something.
                        if regex != None:
                            # The variables we need.
                            username, channel, message = regex.groups()
                            message = message.strip()

                            # Handle ignored users.
                            if isUserIgnored(username):
                                continue

                            # Broadcaster saying something.
                            if handleAdminMessage(username, channel, sock):
                                continue

                            # Validate and print message to the log.
                            if not writeMessage(message):
                                continue

                            # At this point, it's not an admin message, and it's a successful, valid entry.

                            # Increase messages logged.
                            self.messageCount += 1

                            # Generate Markov
                            if (self.messageCount % self.generate_on) == 0:
                                generateAndSendMessage(sock, channel)
                                last_cull = shouldCull(last_cull)
                                self.messageCount = 0
                    except Exception as e:
                        print("Inner")
                        traceback.print_exc() 
                        print(e)
            except Exception as e:
                print("Outer")
                traceback.print_exc() 
                print(e)
                break

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
    stream_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger

if __name__ == '__main__':
    main()