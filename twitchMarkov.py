from emoji import demojize
import datetime
import socket
import markovify
import re
import traceback
import irc.bot


class markovBot(irc.bot.SingleServerIRCBot):

    def __init__(self, config):
        self.percent_unique = config['markov']['percent_unique']
        self.allow_mentions = config['markov']['allow_mentions']
        self.logfile = config['markov']['log_file']
        self.phrases_list = config['markov']['phrases_list']
        self.state_size = config['markov']['state_size']
        self.clear_logs_after = config['markov']['clear_logs_after']
        self.send_messages = config['markov']['send_messages']
        self.generate_on = config['markov']['send_messages']
        self.times_to_try = config['markov']['times_to_try']
        self.unique = config['markov']['unique']
        self.cull_over = config['markov']['cull_over']
        self.time_to_cull = config['markov']['time_to_cull']
        self.blacklist_file = config['markov']['blacklist_file']
        self.blacklist_words = self.load_blacklist(self.blacklist_file)


    def listMeetsThresholdToSave(self, part, whole):
        pF = float(len(part))
        wF = float(len(whole))
        if wF == 0:
            return False
        uniqueness = (pF/wF) * float(100)
        return (uniqueness >= self.percent_unique)

    def filterMessage(self, message):
        if self.checkBlacklisted(message):
            return None
        
        # Remove links
        # TODO: Fix
        message = re.sub(r"http\S+", "", message)

        # Remove mentions
        if self.allow_mentions == False:
            message = re.sub(r"@\S+", "", message)

        # Remove just repeated messages.
        words = message.split()
        # Make list unique
        uniqueWords = list(set(words))
        if not self.listMeetsThresholdToSave(uniqueWords, words):
            return None

        # Space filtering
        message = re.sub(r" +", " ", message)
        message = message.strip()
        return message

    def writeMessage(self, message):
        message = self.filterMessage(message)
        if message != None and message != "":
            if messageCount == 0 and self.clear_logs_after:
                f = open(self.logfile, "w", encoding="utf-8")
            else:
                f = open(self.logfile, "a", encoding="utf-8")
            f.write(message + "\n")
            f.close()
            return True
        return False

    def generateMessage(self):
        with open(self.logfile, encoding="utf-8") as f:
            text = f.read()
        text_model = markovify.NewlineText(text, state_size=self.state_size)
        testMess = None
        if self.unique and (len(self.phrases_list) > 0):
            foundUnique = False
            tries = 0
            while not foundUnique and tries < 20:
                testMess = text_model.make_sentence(tries=self.times_to_try)
                if not (testMess in self.phrases_list):
                    foundUnique = True
                tries += 1
        else:
            testMess = text_model.make_sentence(tries=self.times_to_try)
        if not (testMess is None):
            self.phrases_list.append(testMess)
        else:
            self.phrases_list = [testMess]
        return testMess

    def generateAndSendMessage(self, sock, channel):
        if self.send_messages:
            markoved = self.generateMessage()
            if markoved != None:
                self.sendMessage(sock, channel, markoved)
            else:
                print("Could not generate.")

    def sendMessage(self, sock, channel, message):
        if self.send_messages:
            sock.send("PRIVMSG #{} :{}\r\n".format(channel, message).encode("utf-8"))

    def sendMaintenance(self, sock, channel, message):
        sock.send("PRIVMSG #{} :{}\r\n".format(channel, Conf.SELF_PREFIX + message).encode("utf-8"))

    def handleAdminMessage(self, username, channel, sock):
        if username == channel or username == Conf.owner or username in Conf.mods:
            # Log clearing after message.
            if message == Conf.CMD_CLEAR:
                if self.clear_logs_after == True:
                    self.clear_logs_after = False
                    self.sendMaintenance(sock, channel, "No longer clearing memory after message! betch200IQ")
                else:
                    self.clear_logs_after = True
                    self.sendMaintenance(sock, channel, "Clearing memory after every message! FeelsDankMan")
                return True
            # Wipe logs
            if message == Conf.CMD_WIPE:
                f = open(self.logfile, "w", encoding="utf-8")
                f.close()
                self.sendMaintenance(sock, channel, "Wiped memory banks. D:")
                return True
            # Toggle functionality
            if message == Conf.CMD_TOGGLE:
                if self.send_messages:
                    self.send_messages = False
                    self.sendMaintenance(sock, channel, "Messages will no longer be sent! D:")
                else:
                    self.send_messages = True
                    self.sendMaintenance(sock, channel, "Messages are now turned on! :)")
                return True
            # Toggle functionality
            if message == Conf.CMD_self.unique:
                if self.unique:
                    self.unique = False
                    self.sendMaintenance(sock, channel, "Messages will no longer be unique. PogO")
                else:
                    self.unique = True
                    self.sendMaintenance(sock, channel, "Messages will now be unique. PogU")
                return True
            # Generate message on how many numbers.
            if message.split()[0] == Conf.CMD_SET_NUMBER:
                try:
                    stringNum = message.split()[1]
                    if stringNum != None:
                        num = int(stringNum)
                        if num <= 0:
                            raise Exception
                        self.generate_on = num
                        self.sendMaintenance(sock, channel, "Messages will now be sent after " + self.generate_on + " chat messages. DankG")
                except:
                        self.sendMaintenance(sock, channel, "Current value: " + str(self.generate_on) + ". To set, use: " + str(Conf.CMD_SET_NUMBER) + " [number of messages]")
                return True
            # Check if alive.
            if message == Conf.CMD_ALIVE:
                self.sendMaintenance(sock, channel, "Yeah, I'm alive and learning. betch2IQ")
                return True
            # Kill
            if (username == channel or username == Conf.owner) and message == Conf.CMD_EXIT:
                self.sendMaintenance(sock, channel, "You have killed me. D:")
                exit()
        return False

    def isUserIgnored(self, username):
        if (username in Conf.ignoredUsers):
            return True
        return False

    def cullFile(self):
        fin = open(self.logfile, "r", encoding="utf-8")
        data_list = fin.readlines()
        fin.close()
        
        size = len(data_list)
        if size <= self.cull_over:
            return
        size_delete = size // 2
        del data_list[0:size_delete]
        
        fout = open(self.logfile, "w", encoding="utf-8")
        fout.writelines(data_list)
        fout.close()

    def checkBlacklisted(self, message):
        # Check words that the bot should NEVER learn.
        for i in self.blacklist_words:
            if re.search(r"\b" + i, message, re.IGNORECASE):
                return True
        return False

    def shouldCull(self, last_cull):
        now_time = datetime.datetime.now()
        time_since_cull = now_time - last_cull
        if time_since_cull > self.time_to_cull:
            self.cullFile()
            last_cull = datetime.datetime.now()
        return last_cull

def main():
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

        loop(sock)

def loop(sock):
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
                        messageCount += 1

                        # Generate Markov
                        if (messageCount % self.generate_on) == 0:
                            generateAndSendMessage(sock, channel)
                            last_cull = shouldCull(last_cull)
                            messageCount = 0
                except Exception as e:
                    print("Inner")
                    traceback.print_exc() 
                    print(e)
        except Exception as e:
            print("Outer")
            traceback.print_exc() 
            print(e)
            break

if __name__ == '__main__':
    main()