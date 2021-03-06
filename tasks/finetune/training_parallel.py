# Supress unnecessary warnings so that presentation looks clean
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import os
import csv
import pandas as pd
import matplotlib.pylab as plt
import torch
import torch.nn as nn
from torch.optim.lr_scheduler import ReduceLROnPlateau, CyclicLR
from torch.utils.tensorboard import SummaryWriter
from torchtext import data
from transformers import GPT2Tokenizer, GPT2LMHeadModel
import sys
import time
import logging
logging.basicConfig(level=logging.INFO)


max_len = 20 
batch_size = 64
num_epochs = 10
learning_rate = 0.001
cuda = True
data_dir = '/u/gj3bg/gj3bg/cornell movie-dialogs corpus/'
summary_dir = './tb_summary'

# Set device type
if cuda and torch.cuda.is_available():
    print("Running on GPU")
    device = torch.device("cuda")
else:
    print("Running on CPU")
    device = torch.device("cpu")

print("-" * 84)
print("Running on device type: {}".format(device))

# os.chdir(data_dir)
convtexts = pd.read_csv(data_dir + 'dialogue_training_data.csv', sep=',')
convtexts = np.array(convtexts).tolist()
print("Data Example")
print(convtexts[:1])

# Load pre-trained model tokenizer (vocabulary)
tokenizer = GPT2Tokenizer.from_pretrained('gpt2')
model = GPT2LMHeadModel.from_pretrained('gpt2')
model.to(device)

train_file = data_dir + 'dialogue_training_data.csv'
valid_file  = data_dir + 'dialogue_validation_data.csv'

# # Data Parallelism over 4 GPUs
# if torch.cuda.device_count() > 1:
#     print("Running on ", torch.cuda.device_count(), "GPU's")
#     model = nn.DataParallel(model)
#     model.to(device)
# else:
#     model.to(device)


tokenizer.pad_token = '<PAD>'
pad_index = tokenizer.convert_tokens_to_ids(tokenizer.pad_token)

TEXT = data.Field(use_vocab=False, tokenize=tokenizer.encode, pad_token=pad_index, batch_first =True)
fields = [("src", TEXT), ("trg", TEXT)]

train_data, valid_data = data.TabularDataset.splits(
    path=data_dir,
    train=train_file,
    test=valid_file,
    format="CSV",
    fields=fields,
)

train_iterator, valid_iterator = data.BucketIterator.splits(
    (train_data, valid_data),
    batch_size=batch_size,
    sort_key=lambda x: x.src,
    sort_within_batch=False,
    device=device
)

print("No. of Batches in training data", len(train_iterator))
print("No. of Batches in validation data", len(valid_iterator))

#optimizer = torch.optim.Adam(lr=learning_rate, params=model.parameters())
optimizer = torch.optim.SGD(lr=learning_rate, params=model.parameters(), momentum=0.9)

scheduler = CyclicLR(optimizer, base_lr=learning_rate, max_lr=1, mode="exp_range", gamma=0.9994)

# next(iter(train_iterator))

# for i, batch in enumerate(train_iterator):
#         source = batch.src[2]
#         target = batch.trg[2]
#         print(source)
#         print("Source Given: ", tokenizer.decode(source.tolist()))
#         break

model = GPT2LMHeadModel.from_pretrained('gpt2')
model.to(device)

# Initialize summary writer
writer = SummaryWriter(summary_dir)

# Start Training
training_loss_list = []
validation_loss_list = []
    
print("-" * 84)
print("Start Training")
start_time = time.time()

for epoch in range(num_epochs):
    epoch_start = time.time()
    writer.add_scalar("optim/lr", optimizer.param_groups[0]["lr"], epoch)
    model.train()
    training_loss = 0
    for i, batch in enumerate(train_iterator):
        # Get source and target
        print("epoch", epoch, "i", i, "avg_training_loss_per_batch", training_loss/(i+1))
        source = batch.src
        target = batch.trg
        # Trim source text
        if source.size(1) > max_len:
            source = source[:, :max_len]
        if target.size(1) > max_len:
            target = target[:, :max_len]
        tokens_tensor = torch.tensor(source)              
        for ind in range(target.shape[1]):
            optimizer.zero_grad()
            label = target[:,ind]
            out = model(tokens_tensor)
            out = out[0]
            # print(out[1])
            predictions = torch.softmax(out[:, -1, :], dim = 0)
            predictions = torch.log(predictions)
            loss = nn.functional.nll_loss(predictions, torch.tensor(label))
            #print(loss)
            if not torch.isinf(loss).item():
                training_loss += loss.item()
            loss.backward()
            optimizer.step()
            predicted_index = torch.argmax(predictions, dim = 1)
            tokens_tensor = torch.cat((tokens_tensor, label.unsqueeze(1)), dim = 1)
        #sys.exit()
    print("epoch", epoch, "training_loss_per_epoch", training_loss)
    training_loss_list.append(training_loss)

    # Add training summary to tensorboard
    writer.add_scalar("train/loss", training_loss, epoch)
    for name, params in model.named_parameters():
        # print( "params.requires_grad : ", params.requires_grad)
        if params.requires_grad:
            name = name.replace(".", "/")
            writer.add_histogram(name, params.data, epoch)
    
    #Evaluation on Validation data
    with torch.no_grad():
        model.eval()
        validation_loss = 0
        for i, batch in enumerate(valid_iterator):
            source = batch.src
            target = batch.trg
            if source.size(1) > max_len:
                source = source[:, :max_len]
            if target.size(1) > max_len:
                target = target[:, :max_len] 
            tokens_tensor = torch.tensor(source)                 
            for ind in range(target.shape[1]):
                label = target[:,ind]
                out = model(tokens_tensor)
                out = out[0]
                predictions = torch.softmax(out[:, -1, :], dim = 0)
                predictions = torch.log(predictions)
                loss = nn.functional.nll_loss(predictions, torch.tensor(label))
                if not torch.isinf(loss).item():
                    validation_loss += loss.item()
                predicted_index = torch.argmax(predictions, dim = 1)
                tokens_tensor = torch.cat((tokens_tensor, predicted_index.unsqueeze(1)), dim = 1)
            # Add validation summary to tensorboard
            # if i == 0:
            #     for name, value in model.named_parameters():
            #             name = name.replace(".", "/") + "/grad"
            #             writer.add_histogram(name, value.grad.data, epoch)

        print("epoch", epoch, "validation_loss", validation_loss)
        writer.add_scalar("valid/loss", validation_loss, epoch)
        validation_loss_list.append(validation_loss)
        # Print the predicted text
        predicted_text = tokenizer.decode(tokens_tensor[0].tolist())
        print("Target: ", tokenizer.decode(target[0].tolist()))
        print("Source Given: ", tokenizer.decode(source[0].tolist()))
        print("Predicted: ", predicted_text)
        #scheduler.step(validation_loss) 
        # Save loss in text file
        c = [[i  for i in range(num_epochs)], training_loss_list, validation_loss_list]
        with open("./loss.txt", "a") as file:
            for x in zip(*c):
                file.write("{0}\t{1}\t{2}\n".format(*x)) 
        model_file = './saved_model.pkl'
        #torch.save(model, model_file)
        print("Per epoch Training + Validation Time: {:0.2f} mins".format((time.time() - epoch_start) / 60))  


plt.figure(figsize = (10, 4))
plt.subplot(1, 2, 1)
plt.plot(validation_loss_list, 'bo-', label = 'val-loss')
plt.plot(training_loss_list, 'ro-', label = 'train-loss')
plt.grid('on')
plt.ylabel('loss')
plt.xlabel('epoch')
plt.legend(['validation', 'training'], loc='upper right')
plt.savefig("./Loss_vs_epoch.png")


# writer.add_hparams(
#     {
#         "lr": learning_rate,
#         "seq-len": max_len,
#         "batch-size": batch_size,
#         "num-epochs": num_epochs,
#     },
#     {
#         "train/loss": training_loss,
#         "val/loss": validation_loss,
#     },
# )

print("Total Training + Validation Time: {:0.2f} mins".format((time.time() - start_time) / 60))


model_file = './saved_model.pkl'
#torch.save(model, model_file)
print("training complete")

#Load model for evaluation
# model = torch.load(model_file)
# model.eval()
