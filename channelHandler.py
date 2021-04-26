import os
import markovify
import re
import datetime
import logging

class channelHandler():

    def __init__(self, channel, config, parent):
        self.logger = logging.getLogger(f'markovBot.bot.{channel}')
        self.channel = channel
        self.parent = parent
        self.user_id = self.parent.twitch.get_users(logins=[channel.lower()])['data'][0]['id']
        self.messageCount = 0
        self.message_file = self.getMessageFile()
        self.last_cull = datetime.datetime.now()
        self.clear_logs_after = config['clear_logs_after']
        self.send_messages = config['send_messages']
        self.unique = config['unique']
        self.generate_on = config['generate_on']
    
    def on_pubmsg(self, c, e):
        msg = self.parse_msg_event(e)
        if (msg['mod'] or msg['broadcaster']) and msg['content'][:1] == '!':
            self.handleAdminMessage(msg)
        else:
            pass
        if e.arguments[0].lower().find(self.parent.username.lower()) != -1:
            self.logger.info(f'{msg["name"]}: {e.arguments[0]}')
    
    def parse_msg_event(self, event):
        out = {}
        for tag in event.tags:
            if tag['key'] == "display-name":
                out['name'] = tag['value']
            elif tag['key'] == "user-id":
                out['user_id'] = tag['value']
            elif tag['key'] == "tmi-sent-ts":
                out['time'] = datetime.datetime.fromtimestamp(float(tag['value']))
            elif tag['key'] == 'badges':
                out['broadcaster'] = tag['value'] == 'broadcaster/1'
            elif tag['key'] == tag['user-type']:
                out['mod'] = tag['value'] == '1'
            elif tag['key'] == tag['subscriber']:
                out['subscriber'] = tag['value'] == '1'
        out['content'] = event.arguments[0]
        return out
                
    def sendMessage(self, message):
        self.parent.connection.privmsg('#' + self.channel, message)

    def getMessageFile(self):
        dir = os.path.join(os.path.dirname(__file__), 'messages')
        if not os.path.isdir(dir): os.mkdir(dir)
        f = os.path.join(dir, self.channel)
        if not os.path.exists(f): open(f, "w").close()
        return f
    
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
                self.sendMessage(markoved)
            else:
                self.logger.error("Could not generate.")

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
    
    def handleAdminMessage(self, msg):
        cmd = msg['content'].split(' ')[0][1:].lower()
        if cmd == 'clear':
            if self.clear_logs_after:
                self.clear_logs_after = False
                self.parent.config.save()
                self.sendMessage("No longer clearing memory after message! betch200IQ")
            else:
                self.clear_logs_after = True
                self.parent.config.save()
                self.sendMessage("Clearing memory after every message! FeelsDankMan")
        elif cmd == 'wipe':
            open(self.message_file, "w").close()
            self.sendMessage("Wiped memory banks. D:")
        elif cmd == 'toggle':
            if self.send_messages:
                self.send_messages = False
                self.parent.config.save()
                self.sendMessage("Messages will no longer be sent! D:")
            else:
                self.send_messages = True
                self.parent.config.save()
                self.sendMessage("Messages are now turned on! :)")
        elif cmd == 'unique':
            if self.unique:
                self.unique = False
                self.parent.config.save()
                self.sendMessage("Messages will no longer be unique. PogO")
            else:
                self.unique = True
                self.parent.config.save()
                self.sendMessage("Messages will now be unique. PogU")
        elif cmd == 'setafter':
            try:
                stringNum = msg['content'].split(' ')[1]
                if stringNum != None:
                    num = int(stringNum)
                    if num <= 0:
                        raise Exception
                    self.generate_on = num
                    self.parent.config.save()
                    self.sendMessage("Messages will now be sent after " + self.generate_on + " chat messages. DankG")
            except:
                    self.sendMessage("Current value: " + str(self.generate_on) + ". To set, use: setafter [number of messages]")
        elif cmd == 'isalive':
            self.sendMessage("Yeah, I'm alive and learning. betch2IQ")
        elif cmd == 'kill':
            self.sendMessage("You have killed me. D:")
            exit()