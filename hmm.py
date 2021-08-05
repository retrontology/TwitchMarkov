from sklearn.preprocessing import LabelEncoder
from hmmlearn import hmm
import numpy as np
from nltk import FreqDist
import sqlite3

HIDDEN_STATES = 8
DB_FILE = 'messages/rlly.db'
DB_TIMEOUT = 10

connection = sqlite3.connect(DB_FILE, timeout=DB_TIMEOUT)
cursor = connection.cursor()
messages = [x[0] for x in cursor.execute('SELECT message from messages').fetchall()]
cursor.close()
connection.close()

vocab = set('\n')
words = list()
lengths = list()
for message in messages:
    w = message.split(' ')
    vocab.update([word for word in w])
    w.append('\n')
    words.extend(w)
    lengths.append(len(w))
print(len(words))
label_encoder = LabelEncoder()
label_encoder.fit(list(vocab))

sequences = label_encoder.transform(words)
features = np.fromiter(sequences, np.int64)
features = np.atleast_2d(features).T
freq_dist = FreqDist(sequences)

model = hmm.MultinomialHMM(n_components=HIDDEN_STATES, init_params='ste')
model = model.fit(features, lengths)

ids, states = model.sample(80)
output = label_encoder.inverse_transform(np.squeeze(ids))
output = ' '.join(output)
print(output)