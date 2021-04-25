import os
import markovify
import re

class channelHandler():

    def __init__(self, channel, config, parent):
        self.channel = channel
        self.parent = parent
        self.messageCount = 0
        self.message_file = self.getMessageFile()
    
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