import os
import markovify
import re
import datetime

class channelHandler():

    def __init__(self, channel, config, parent):
        self.channel = channel
        self.parent = parent
        self.messageCount = 0
        self.message_file = self.getMessageFile()
        self.last_cull = datetime.datetime.now()

    
    def sendMessage(self):
        pass

    def getMessageFile(self):
        dir = os.path.join(os.path.dirname(__file__), 'messages')
        if not os.path.isdir: os.mkdir(dir)
        return os.path.join(dir, self.channel)
    
    def generateMessage(self):
        with open(self.message_file, encoding="utf-8") as f:
            text = f.read()
        text_model = markovify.NewlineText(text, state_size=self.parent.state_size)
        testMess = None
        if self.parent.unique and (len(self.phrases_list) > 0):
            foundUnique = False
            tries = 0
            while not foundUnique and tries < 20:
                testMess = text_model.make_sentence(tries=self.parent.times_to_try)
                if not (testMess in self.phrases_list):
                    foundUnique = True
                tries += 1
        else:
            testMess = text_model.make_sentence(tries=self.parent.times_to_try)
        if not (testMess is None):
            self.phrases_list.append(testMess)
        else:
            self.phrases_list = [testMess]
        return testMess

    def generateAndSendMessage(self, channel):
        if self.send_messages:
            markoved = self.generateMessage()
            if markoved != None:
                self.sendMessage(channel, markoved)
            else:
                print("Could not generate.")

    def writeMessage(self, message):
        message = self.filterMessage(message)
        if message != None and message != "":
            if self.messageCount == 0 and self.parent.clear_logs_after:
                f = open(self.message_file, "w", encoding="utf-8")
            else:
                f = open(self.message_file, "a", encoding="utf-8")
            f.write(message + "\n")
            f.close()
            return True
        return False
    
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
    
    def shouldCull(self, last_cull):
        now_time = datetime.datetime.now()
        time_since_cull = now_time - last_cull
        if time_since_cull > self.time_to_cull:
            self.cullFile()
            last_cull = datetime.datetime.now()
        return last_cull
    
    def handleAdminMessage(self, username, channel):
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