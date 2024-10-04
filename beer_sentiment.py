# -*- coding: utf-8 -*-
"""Copy of beer_sentiment.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/10Tw-R6HP20pXYlBWuADiVr2ReWlxHufB

# Beer Review Classification with Hierarchical Self-Attention Networks

## 1. Setup and Dependencies
"""

import torch
from scipy.sparse import csr_matrix
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from collections import OrderedDict
from torch.nn.modules.module import Module
from torch.utils.data import TensorDataset
import time
import numpy as np
import collections
import pickle
import argparse
from random import shuffle
import math
import numpy as np
import matplotlib.pyplot as plt
import json
import sys
import datetime
import string
import nltk
from nltk import word_tokenize, sent_tokenize
from sklearn.preprocessing import LabelEncoder, LabelBinarizer
from sklearn.model_selection import train_test_split
from operator import itemgetter
from torch.autograd import Variable
from zipfile import ZipFile

nltk.download('punkt')

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

"""## 2. Data Inspection"""

datadir = "/content/drive/MyDrive/ML CLASS/HW7/"

# Load the data
with ZipFile(datadir+'labeled.json.zip', 'r') as ZZ:
    for filename in ZZ.namelist():
        with ZZ.open(filename, 'r') as f:
            beer_reviews = json.load(f)

# Dictionary to store overall ratings for each beer and brewer
beer_ratings = {}
brewer_ratings = {}

# Extract overall ratings for each beer and brewer
for review in beer_reviews:
    beer_name = review['beer_name']
    brewer_name = review['brewer']
    overall_rating = review['overall']

    # Update beer ratings
    if beer_name not in beer_ratings:
        beer_ratings[beer_name] = []
    beer_ratings[beer_name].append(overall_rating)

    # Update brewer ratings
    if brewer_name not in brewer_ratings:
        brewer_ratings[brewer_name] = []
    brewer_ratings[brewer_name].append(overall_rating)

# Statistics for beers
beer_stats = {}
for beer_name, ratings in beer_ratings.items():
    beer_stats[beer_name] = {
        'mean': np.mean(ratings),
        'median': np.median(ratings),
        'std_dev': np.std(ratings)
    }

# Statistics for brewers
brewer_stats = {}
for brewer_name, ratings in brewer_ratings.items():
    brewer_stats[brewer_name] = {
        'mean': np.mean(ratings),
        'median': np.median(ratings),
        'std_dev': np.std(ratings)
    }

# Print
print("Beer Statistics:")
for beer_name, stats in beer_stats.items():
    print(f"Beer: {beer_name}, Mean: {stats['mean']}, Median: {stats['median']}, Std Dev: {stats['std_dev']}")

print("\nBrewer Statistics:")
for brewer_name, stats in brewer_stats.items():
    print(f"Brewer: {brewer_name}, Mean: {stats['mean']}, Median: {stats['median']}, Std Dev: {stats['std_dev']}")

"""## 3. Prepare Vocabulary and Embeddings"""

def prep_vocab_emb():
    vocab = 'word2idx_small'
    with open(datadir+vocab+'.json', 'r') as f:
        w2i = json.load(f)
        num_words = len(w2i.keys())
        print('NUM WORDS', num_words)

    # Load pre-trained word embeddings
    word2vec = {}
    start = time.time()
    with ZipFile(datadir+'glove.6B.50d.txt.zip', 'r') as ZZ:
        for filename in ZZ.namelist():
            with ZZ.open(filename, 'r') as f:
                for i, line in enumerate(f):
                    values = line.split()
                    word = values[0]
                    vec = np.asarray(values[1:], dtype='float32')
                    word2vec[word] = vec

    # Prepare embedding matrix
    WordEmbeddings = np.zeros((num_words+1, 50))
    for word, i in w2i.items():
        if word in word2vec:
            WordEmbeddings[i] = word2vec[word]

    return WordEmbeddings, w2i

"""## 4. Text Preprocessing Functions"""

def remove_punctuation(s):
    return s.translate(str.maketrans('', '', string.punctuation+"\n"))

def ConvertSentence2Word(s):
    return word_tokenize(remove_punctuation(s).lower())

def ConvertSent2Idx(s):
    s_temp = [w for w in ConvertSentence2Word(s) if w in w2i]
    temp = [w2i[w] for w in s_temp]
    return temp

def ConvertDoc2List(doc):
    temp_doc = sent_tokenize(doc)
    temp = [ConvertSent2Idx(sentence) for sentence in temp_doc if len(ConvertSent2Idx(sentence)) >= 1]
    return temp

def ConvertList2Array(docs):
    ms = len(docs)
    mw = len(max(docs, key=len))
    result = np.zeros((ms, mw))
    for i, line in enumerate(docs):
        for j, word in enumerate(line):
            result[i, j] = word
    return result

def data_to_array(X_t, Y_t):
    X_t_data = []
    Y_t_data = []
    p = len(w2i.keys())
    for i in range(len(X_t)):
        X_input = ConvertDoc2List(X_t[i])
        if len(X_input) < 1:
            continue
        X_input = torch.LongTensor(ConvertList2Array(X_input))
        Y_t_data.append(Y_t[i])
        X_t_data.append(X_input.to(device))
    Y_t_data = torch.tensor(np.array(Y_t_data).reshape((-1, 1))).type(torch.long).to(device)
    return X_t_data, Y_t_data

"""## 5. Load and Split Data"""

def load_data(num, corpus):
    if corpus == 'beer':
        with ZipFile(datadir+'labeled.json.zip', 'r') as ZZ:
            for filename in ZZ.namelist():
                with ZZ.open(filename, 'r') as f:
                    brv = json.load(f)

        X = []
        Y = []
        for i, b in enumerate(brv):
            if i < num:
                X.append(b['review'])
                v = b['overall']
                y = 0
                if v >= 14:
                    y = 1
                Y.append(y)
        del brv
    else:
        npz = np.load(datadir + 'yelp_review_small.npz', allow_pickle=True)
        data = npz['arr_0']
        X = data[:, 0]  # Text
        Y = data[:, 1]  # Label
        Y = Y - 1
        del data
    return X, Y

def get_data(X, Y):
    X, Y = data_to_array(X, Y)
    ii = np.int64(np.arange(0, len(X), 1))
    np.random.shuffle(ii)
    XX = [X[i] for i in ii]
    X = XX
    Y = Y[ii]
    num = len(X)
    nntr = np.int32(.8 * num)
    nnva = np.int32(.82 * num)
    X_train_data = X[0:nntr]
    y_train_data = Y[0:nntr]
    X_val_data = X[nntr:nnva]
    y_val_data = Y[nntr:nnva]
    X_test_data = X[nnva:num]
    y_test_data = Y[nnva:num]
    return X_train_data, y_train_data, X_val_data, y_val_data, X_test_data, y_test_data

num=10000
X,Y=load_data(num,'beer')
len(X)

WordEmbeddings, w2i=prep_vocab_emb()
X_train_data,  y_train_data, X_val_data,  y_val_data, X_test_data, y_test_data = get_data(X,Y)

"""## 6. Define the Models
### Attension layer and target attension

"""

class SelfAttention(nn.Module):
    def __init__(self, d_model):
        super(SelfAttention, self).__init__()
        self.d_model = d_model
        self.q_linear = nn.Linear(d_model, d_model)
        self.v_linear = nn.Linear(d_model, d_model)
        self.k_linear = nn.Linear(d_model, d_model)

    def forward(self, x):
        k = self.k_linear(x)
        q = self.q_linear(x)
        v = self.v_linear(x)
        scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.d_model)
        scores = F.softmax(scores, dim=-1)
        scores = torch.matmul(scores, v)
        return scores

class TargetAttention(Module):
    def __init__(self, input_dim,dropout_rate):
        super(TargetAttention, self).__init__()
        # define the transfer embedding vector T\in R^{1*d}
        self.target = nn.Parameter(torch.empty((1,input_dim)))
        nn.init.kaiming_uniform_(self.target)
        self.input_dim=input_dim
        self.sq_input_dim = np.sqrt(input_dim)
        self.dropout = nn.Dropout(dropout_rate)

    #define the target attention process: softmax(T*V^T/sqrt(d))*V
    def target_att(self, t, k, v):
        # Dimensions: batch_size x 1 x number_of_tokens
        out=torch.matmul(t, k.permute(0,2,1))/self.sq_input_dim
        sf=torch.softmax(out,2)
        # Dimensions: batch_size x 1 x embedd_dim
        targ=torch.matmul(sf,v)
        # Dimensions: batch_size x embedd_dim x 1
        targ= targ.permute(0, 2, 1)
        return targ

    def forward(self, inputk, input):
        batch_size = input.size(0)
        # Make the target parameter have the same nunber of dimensions as the inputk, input.
        output = self.target_att(self.target.expand(batch_size, 1, self.input_dim), inputk, input)

        return output

"""### Convolutional Cell"""

class ConvolutionalCELL(nn.Module):
    def __init__(self, input_dim, kernel_dim, dropout_rate):
        super(ConvolutionalCELL, self).__init__()
        self.input_dim = input_dim
        self.conv1d = nn.Conv1d(input_dim, input_dim, kernel_size=3, padding=1)
        self.dropout = nn.Dropout(dropout_rate)

    def forward(self, input):
        # input: [batch_size, sequence_length, input_dim]
        x = input.permute(0, 2, 1)  # Reshape for convolution: [batch_size, input_dim, sequence_length]
        conv_output = self.conv1d(x)
        conv_output = F.relu(conv_output)
        conv_output = self.dropout(conv_output)  # Apply dropout

        # Reshape back to original shape: [batch_size, input_dim, sequence_length]
        conv_output = conv_output.permute(0, 2, 1)

        output = F.layer_norm(conv_output + input, conv_output.size()[1:])

        return output

"""### Self attension cell

"""

class CELL(nn.Module):
    def __init__(self, input_dim, kernel_dim, dropout_rate): #convc_cnt=1
        super(CELL, self).__init__()
        self.input_dim = input_dim
        self.cell = SelfAttention(input_dim)
        self.dropout = nn.Dropout(dropout_rate)

    def forward(self, input):
        x=input
        hidden= F.relu(self.dropout(self.cell(x))+x)
        output = F.layer_norm(hidden, hidden.size()[1:])

        return output

class Hierarchical(nn.Module):
    def __init__(self, num_emb, input_dim, dropout_rate, pretrained_weight, untrained_weight):
        super(Hierarchical, self).__init__()
        # Define the initialization of embedding matrix
        # One is using the pretrained weight matrix, the other is initialized randomly.
        self.id2vec_pretrained = nn.Embedding(num_emb, 50, padding_idx=1)
        self.id2vec_pretrained.weight.data.copy_(pretrained_weight)
        self.id2vec_pretrained.weight.requires_grad=False
        self.id2vec_untrained = nn.Embedding(num_emb, 50, padding_idx=1)
        self.id2vec_untrained.weight.data.copy_(untrained_weight)
        self.id2vec_untrained.requires_grad = True
        self.dropout = nn.Dropout(dropout_rate)

        self.loss=nn.CrossEntropyLoss()

    def accuracy(self,y_pred,y):
        _, pred=y_pred.max(1)
        acc=pred.eq(y)

        return acc

class HSAN(Hierarchical):
    def __init__(self, input_dim, num_class, kernel_dim,
                  dropout_rate, num_emb, pretrained_weight, untrained_weight, ltype="SA"):
        super(HSAN, self).__init__(num_emb, input_dim, dropout_rate, pretrained_weight, untrained_weight)

        self.ltype=ltype
        if ltype == "SA":
            self.cell = CELL(input_dim, kernel_dim, dropout_rate)
        elif ltype == "CO":
            self.cell = ConvolutionalCELL(input_dim, kernel_dim, dropout_rate)
        else:
            raise ValueError("Invalid ltype value. Allowed values are 'SA' and 'CO'.")

        self.taw = TargetAttention(input_dim, dropout_rate)
        self.tas = TargetAttention(input_dim, dropout_rate)
        self.dropout = nn.Dropout(dropout_rate)
        self.cls = nn.Linear(input_dim, num_class)
        nn.init.xavier_normal_(self.cls.weight)

    def predict(self, x):

        # Get embedding produce an array of number_of_sentences x number_of_words x embedd_dim.
        input = self.id2vec_untrained(x)

        # Word level self-attention
        # Out Dim: number_of_sentences x number_of_words x embedd_dim
        hiddenw = self.cell(input)

        # Out Dim: number_of_sentences x embedd_dim x 1
        hiddenw = self.taw(hiddenw, hiddenw)

        # Out Dim: 1 x number_of_sentences x embedd_dim (batch_size = 1)
        hiddenw = hiddenw.permute(2, 0, 1)

        # Sentence level self-attention
        # Out Dim: 1 x number_of _sentences x embedd_dim
        hiddens = self.cell(hiddenw)

        # Out Dim: 1 x embedd_dim  x 1
        hiddens = self.tas(hiddens, hiddens)

        # Get logits
        logits = self.cls(hiddens.squeeze(-1))

        return logits

    def forward(self, x,  y):
        logits = self.predict(x)
        if logits.shape[1] == 1:
            logits = torch.cat((-logits, logits), dim=1)
        loss = self.loss(logits, y)
        accuracy = self.accuracy(logits, y)
        return loss, accuracy

def val_score(model, data, labels):
    #Test the model accuracy for the test data set (or valid data set)
    correct = 0.
    #l = labels.shape[1]
    for i in range(len(data)):

        val_pred = model.predict(data[i])

        #torch.Tensor([np.argmax(y).squeeze()])
        acc = model.accuracy(val_pred, labels[i])
        correct = correct + acc # Compute the total correct number
    val_acc = correct/len(data)

    return val_acc

"""## 7. Training of Convolutional Cell and Self Attension Cell and Evaluation"""

def run_epochs(model,X_train_data, y_train_data, optimizer,step=0):

  bestscore = 0.
  seed=14543
  torch.manual_seed(seed)
  np.random.seed(seed)
  print("Traing data size:",len(y_train_data))

  n_epochs = 5 # When we remove the dropout layer and softmax layer, it converges fast.
  model.train()
  train_acc=[]
  valid_acc=[]
  # Then we run the model in each epochs.
  num_train=len(X_train_data)
  ii=list(range(num_train))
  t1=time.time()
  end=time.time()
  for epoch in range(n_epochs):
      start = time.time()
      np.random.shuffle(ii)
      accuracy = 0.
      tot_loss=0.
      for i,j in enumerate(ii):

          optimizer.zero_grad()
          loss, cor = model.forward(x=X_train_data[j],y=y_train_data[j])
          loss.backward()
          optimizer.step()
          accuracy = accuracy + cor.item()
          tot_loss+=loss.item()
          if (np.mod(i,5000)==0 or i==num_train-1) and i>0:
            val_sc=val_score(model, X_val_data, y_val_data)
            t2=time.time()
            print("iter %i, loss, %.3f, training accuracy: %.2f, validation accuracy: %.2f, time: %.3f" % (
              i, tot_loss/i,accuracy/i, val_sc,t2-t1))
            t1=t2
      accuracy = accuracy / num_train
      train_acc.append(accuracy)
      # test the model on the valid set
      model = model.eval()
      valscore = val_score(model,X_val_data,y_val_data)
      model = model.train()
      valid_acc.append(valscore)

      # save the best model
      if valscore >= bestscore:
          bestscore = valscore
          save_path = torch.save(model,datadir+"models/beer_py_small_"+model.ltype+"_step"+str(epoch)+".pkl")
      temptime = datetime.timedelta(seconds=round(time.time() - start))
      print("epoch %i, training accuracy: %.2f, validation accuracy: %.2f," % (
          epoch + 1, accuracy * 100, valscore * 100), "time: ", temptime)
      accuracy = 0

  totaltime = datetime.timedelta(seconds=round(time.time() - end))
  testscore = val_score(model, X_test_data, y_test_data)
  print("\ntest accuracy: %.2f" % (testscore*100),"%")
  print("\nTime:", totaltime)
  return model, train_acc, valid_acc

def setup_model(WordEmbeddings,ltype="SA"):
    # Set the parameters
    input_dim = WordEmbeddings.shape[1] # = 50
    kernel_dim = 3  #
    num_words = WordEmbeddings.shape[0] # number of words in the embedding matrix
    dropout_rate = 0.1
    pretrained_weight = torch.Tensor(WordEmbeddings) # Word Embedding matrix 1
    untrained_weight = torch.Tensor(WordEmbeddings.shape[0],WordEmbeddings.shape[1])
    untrained_weight = nn.init.xavier_normal_(untrained_weight) # Word Embedding matrix 2
    num_class = 2

    # Define the model
    model = HSAN(input_dim, num_class, kernel_dim,
                dropout_rate, num_words, pretrained_weight, untrained_weight,ltype=ltype)
    optimizer=torch.optim.Adam(model.parameters()) # define the optimizer function
    num=0
    for k,p in model.named_parameters():
       if p.requires_grad:
         print(k,p.shape)
         num+=p.numel()
    print('number of paramters',num)
    # If we use gpu to run the model.
    model = model.to(device)
    return model, optimizer

# Running Self-Attention Cell
print("Running Self-Attention Cell")
self_att_model, optimizer = setup_model(WordEmbeddings, ltype="SA")
self_att_model, _, _ = run_epochs(self_att_model, X_train_data, y_train_data, optimizer)

# Running Convolutional Cell
print("\nRunning Convolutional Cell")
conv_model, optimizer = setup_model(WordEmbeddings, ltype="CO")
conv_model, _, _ = run_epochs(conv_model, X_train_data, y_train_data, optimizer)

"""To compare, the convolutional cell runs slightly faster than the self attension cell. This makes sense as the self attention cell has relatively more parameters (612352) than the convolutional cell (612252).

The final accuracy is slightly better for HSAN but both compareble (80% vs 78.5%).

## 8. Self Attention with Pretrained embeddings
"""

class Hierarchical_2(nn.Module):
    def __init__(self, num_emb, input_dim, dropout_rate, pretrained_weight, untrained_weight):
        super(Hierarchical_2, self).__init__()
        # Define the initialization of embedding matrix
        # One is using the pretrained weight matrix, the other is initialized randomly.
        self.id2vec_pretrained = nn.Embedding(num_emb, 50, padding_idx=1)
        self.id2vec_pretrained.weight.data.copy_(pretrained_weight)
        self.id2vec_pretrained.weight.requires_grad=False

        if untrained_weight is not None:  # Check if untrained_weight is not None
            self.id2vec_untrained = nn.Embedding(num_emb, 50, padding_idx=1)
            self.id2vec_untrained.weight.data.copy_(untrained_weight)
            self.id2vec_untrained.requires_grad = True
        else:
            self.id2vec_untrained = None

        self.dropout = nn.Dropout(dropout_rate)
        self.loss = nn.CrossEntropyLoss()

    def accuracy(self,y_pred,y):
        # compute the number of correct of the prediction.
        _, pred = y_pred.max(1)
        acc = pred.eq(y)

        return acc


class HSAN_2(Hierarchical_2):
    def __init__(self, input_dim, num_class, kernel_dim,
                  dropout_rate, num_emb, pretrained_weight, untrained_weight=None, ltype="SA"):
        super(HSAN_2, self).__init__(num_emb, input_dim, dropout_rate, pretrained_weight, untrained_weight)

        self.ltype = ltype
        if ltype == "SA":
            self.cell = CELL(input_dim, kernel_dim, dropout_rate)
        elif ltype == "Conv":  # Conditionally use ConvolutionalCELL when ltype is "Conv"
            self.cell = ConvolutionalCELL(input_dim, kernel_dim, dropout_rate)
        else:
            raise ValueError("Invalid ltype value. Allowed values are 'SA' and 'Conv'.")

        self.saw = self.cell
        self.sas = self.cell

        self.taw = TargetAttention(input_dim, dropout_rate)
        self.tas = TargetAttention(input_dim, dropout_rate)
        self.dropout = nn.Dropout(dropout_rate)
        self.cls = nn.Linear(input_dim, num_class)
        nn.init.xavier_normal_(self.cls.weight)

        # Initialize the untrained embedding layer if untrained_weight is not None
        if untrained_weight is not None:
            self.id2vec_untrained.weight.data.copy_(untrained_weight)
            self.id2vec_untrained.requires_grad = True

    def predict(self, x):

        # Get embedding if id2vec_untrained is not None
        if self.id2vec_untrained is not None:
            input = self.id2vec_untrained(x)
        else:
            input = self.id2vec_pretrained(x)  # Use pretrained embeddings if untrained_weight is None

        hiddenw = self.saw(input)
        hiddenw = self.taw(hiddenw, hiddenw)
        hiddenw = hiddenw.permute(2, 0, 1)
        hiddens = self.sas(hiddenw)
        hiddens = self.tas(hiddens, hiddens)
        logits = self.cls(hiddens.squeeze(-1))
        return logits

    def forward(self, x,  y):
        logits = self.predict(x)
        if logits.shape[1] == 1:
            logits = torch.cat((-logits, logits), dim=1)
        loss = self.loss(logits, y)
        accuracy = self.accuracy(logits, y)
        return loss, accuracy

def setup_model_pretrained_embeddings(WordEmbeddings, ltype="SA"):
    input_dim = WordEmbeddings.shape[1]
    kernel_dim = 3
    num_words = WordEmbeddings.shape[0]
    dropout_rate = 0.1
    pretrained_weight = torch.Tensor(WordEmbeddings)  # Use pretrained embeddings

    # For pretrained embeddings, we set untrained_weight to None
    untrained_weight = None

    num_class = 2

    # Define the model with pretrained embeddings
    model = HSAN_2(input_dim, num_class, kernel_dim,
                 dropout_rate, num_words, pretrained_weight, untrained_weight, ltype=ltype)
    optimizer = torch.optim.Adam(model.parameters())

    # Print the number of parameters being updated
    num_updated_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print("Number of parameters being updated:", num_updated_params)

    model = model.to(device)
    return model, optimizer

# Run the model using only pretrained embeddings
print("Running with pretrained embeddings")
pretrained_model, optimizer = setup_model_pretrained_embeddings(WordEmbeddings, ltype="SA")
pretrained_model, _, _ = run_epochs(pretrained_model, X_train_data, y_train_data, optimizer)

"""Compare to the untrained SA, which has 612352 parameters, the pretrained SA has way less parameters (7852).  The pretrained weights version has a worse accuracy."""

