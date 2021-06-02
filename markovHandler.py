from emoji import demojize
import retroBot.channelHandler
import os
import markovify
import re
import datetime
import sqlite3

class markovHandler(retroBot.channelHandler):

    def __init__(self, channel, parent):
        super(markovHandler, self).__init__(channel, parent)
        self.user_id = parent.twitch.get_users(logins=[channel.lower()])['data'][0]['id']
        self.message_count = 0
        self.initMessageDB()
        self.last_cull = datetime.datetime.now()
        self.phrases_list = []
        self.clear_logs_after = parent.config['twitch']['channels'][channel]['clear_logs_after']
        self.send_messages = parent.config['twitch']['channels'][channel]['send_messages']
        self.unique = parent.config['twitch']['channels'][channel]['unique']
        self.generate_on = parent.config['twitch']['channels'][channel]['generate_on']
        self.ignored_users = [x.lower() for x in self.parent.config['twitch']['channels'][channel]['ignored_users']]
        self.initCooldowns()
        
    def initCooldowns(self):
        self.cooldowns = {}
        self.last_used = {}
        self.cooldowns['speak'] = 300
        self.last_used['speak'] = datetime.datetime.fromtimestamp(0)
        self.cooldowns['commands'] = 300
        self.last_used['commands'] = datetime.datetime.fromtimestamp(0)
        self.cooldowns['reply'] = 120
        self.last_used['reply'] = datetime.datetime.fromtimestamp(0)

    def initMessageDB(self):
        self.db_timeout = 10
        dir = os.path.join(os.path.dirname(__file__), 'messages')
        if not os.path.isdir(dir): os.mkdir(dir)
        self.db_file = os.path.join(dir, f'{self.channel.lower()}.db')
        connection = sqlite3.connect(self.db_file, timeout=self.db_timeout)
        sqlite3.register_adapter(bool, int)
        sqlite3.register_converter("BOOLEAN", lambda v: bool(int(v)))
        cursor = connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('create table if not exists messages(date timestamp, user_id integer, name text, mod BOOLEAN, message text)')
        connection.commit()
        cursor.close()
        connection.close()
    
    def on_pubmsg(self, c, e):
        msg = self.parse_msg_event(e)
        if msg['name'].lower() in self.ignored_users:
            pass
        elif msg['content'][:1] == '!':
            self.handleCommands(msg)
        elif msg['content'].lower().find(f'@{self.parent.username.lower()}') != -1:
            self.logger.info(f'{msg["name"]}: {msg["content"]}')
            if (datetime.datetime.now() - self.last_used['reply']).total_seconds() >= self.cooldowns['reply']:
                self.generateAndSendMessage(msg['name'])
                self.last_used['reply'] = datetime.datetime.now()
        else:
            self.writeMessage(msg)
        if self.message_count >= self.generate_on:
            self.generateAndSendMessage()
    
    def generateMessage(self):
        connection = sqlite3.connect(self.db_file, timeout=self.db_timeout)
        cursor = connection.cursor()
        text = '\n'.join([x[0] for x in cursor.execute('SELECT message from messages').fetchall()])
        cursor.close()
        connection.close()
        text_model = markovify.NewlineText(text, state_size=self.parent.state_size)
        testMess = None
        if self.unique and (len(self.phrases_list) > 0):
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

    def generateAndSendMessage(self, target=None):
        try:
            self.message_count = 0
            markoved = self.generateMessage()
        except Exception as e:
            self.logger.error(e)
            markoved = None
        if markoved != None:
            if target != None:
                markoved = f'@{target} {markoved}'
            self.logger.info(f'Generated: {markoved}')
            if self.send_messages: self.send_message(markoved)
        else:
            self.logger.error("Could not generate.")
        self.checkCull()

    def writeMessage(self, msg):
        message = self.filterMessage(msg['content'])
        if message != None and message:
            connection = sqlite3.connect(self.db_file, timeout=self.db_timeout)
            cursor = connection.cursor()
            if self.message_count == 0 and self.clear_logs_after:
                cursor.execute('delete from messages')
                connection.commit()
                cursor.execute('vacuum')
            cursor.execute('insert into messages values (?, ?, ?, ?, ?)', (msg['time'], msg['user_id'], msg['name'], msg['mod'], message))
            connection.commit()
            cursor.close()
            connection.close()
            self.message_count += 1
            return True
        return False
    
    def filterMessage(self, message):
        message = demojize(message)
        if self.parent.checkBlacklisted(message):
            return False
        # Remove links
        # TODO: Fix
        message = re.sub(r"http\S+", "", message)
        # Remove mentions
        if self.parent.allow_mentions == False:
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
    
    def listMeetsThresholdToSave(self, part, whole):
        pF = float(len(part))
        wF = float(len(whole))
        if wF == 0:
            return False
        uniqueness = (pF/wF) * float(100)
        return (uniqueness >= self.parent.percent_unique)

    def cullFile(self):
        connection = sqlite3.connect(self.db_file, timeout=self.db_timeout)
        cursor = connection.cursor()
        size = cursor.execute('select count(*) from messages').fetchall()[0][0]
        self.logger.debug(f'Size of messages: {size}')
        if size > self.parent.cull_over:
            size_delete = size // 2
            self.logger.debug(f'Culling rows below: {size_delete}')
            cursor.execute('delete from messages where rowid < ?', (size_delete,))
            connection.commit()
            cursor.execute('vacuum')
        cursor.close()
        connection.close()
    
    def checkCull(self):
        now_time = datetime.datetime.now()
        time_since_cull = now_time - self.last_cull
        self.logger.debug(f'Time since last cull: {time_since_cull.total_seconds()}')
        if time_since_cull.total_seconds() > self.parent.time_to_cull:
            self.cullFile()
            self.last_cull = datetime.datetime.now()
    
    def handleCommands(self, msg):
        cmd = msg['content'].split(' ')[0][1:].lower()
        if cmd == 'commands' and (datetime.datetime.now() - self.last_used[cmd]).total_seconds() >= self.cooldowns[cmd]:
            self.sendMessage('You can find a list of my commands here: https://retrohollow.com/markov/commands.html')
            self.last_used[cmd] = datetime.datetime.now()
        elif cmd == 'speak' and (datetime.datetime.now() - self.last_used[cmd]).total_seconds() >= self.cooldowns[cmd]:
            self.generateAndSendMessage()
            self.last_used[cmd] = datetime.datetime.now()
        if msg['mod'] or msg['broadcaster']:
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
                connection = sqlite3.connect(self.db_file, timeout=self.db_timeout)
                cursor = connection.cursor()
                cursor.execute('delete from messages')
                connection.commit()
                cursor.execute('vacuum')
                cursor.close()
                connection.close()
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