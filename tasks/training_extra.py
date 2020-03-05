# Supress unnecessary warnings so that presentation looks clean
import warnings
warnings.filterwarnings('ignore')

# import sys
# sys.path.append('transformer')
import torch
from torch import nn
import torch.nn.functional as F
from torchtext import data, datasets
from argparse import ArgumentParser
# from torch.utils.tensorboard import SummaryWriter
import tqdm     # CLI progress bar
import pandas as pd
import numpy as np
import matplotlib.pylab as plt
from transformers import GPT2Tokenizer, GPT2LMHeadModel
from tasks.decoder import top_p_sampling

TEXT = data.Field(lower=True, include_lengths=True, batch_first=True)
LABEL = data.Field(sequential=False)
NUM_CLASS = 2
batch_size = 1

"""
Creates and trains a basic transformer for the IMDB sentiment classification task.
"""
def main(arg):

    cuda_flag = False
    device = 'cuda' if cuda_flag and torch.cuda.is_available() else 'cpu'
    print("Device: ", device)

    convtexts = pd.read_csv('.data/dialogue_data.tsv', sep='\t')
    convtexts = np.array(convtexts)[:2].tolist()
    train_data_loader = torch.utils.data.DataLoader(convtexts, batch_size=batch_size, shuffle=True)
    validation_data_loader = torch.utils.data.DataLoader(convtexts, batch_size=batch_size, shuffle=False)

    it = 0
    for source, target in train_data_loader:
        if it == 192 or it == 191 or it == 193:
            print('Source', source)
            print(len(source[0].split()))
            print('Target', target)
            break
        it += 1

    print('num of training examples: ', len(train_data_loader))
    print('num of test examples: ', len(validation_data_loader))
    if arg.max_length < 0:
        mx = max([max([len(si) for si in s]) for s,t in train_data_loader])
        mx = mx * 2
    else:
        mx = arg.max_length
    print('maximum seq length: ', mx)

    # Load pre-trained model tokenizer (vocabulary)
    tokenizer = GPT2Tokenizer.from_pretrained('gpt2')
    model = GPT2LMHeadModel.from_pretrained('gpt2')

    if device == 'cuda':
        model.cuda()

    optim = torch.optim.Adam(lr=arg.lr, params=model.parameters())
    sched = torch.optim.lr_scheduler.LambdaLR(optim, lambda i: min(i / (arg.lr_warmup / arg.batch_size), 1.0))

    # Training loop
    seen = 0
    training_loss_list = []
    validation_loss_list = []
    for epoch in range(arg.num_epochs):
        print("\n Epoch: ", epoch)
        model.train(True)
        training_loss = 0
        batch_count = 0
        for source_list, target_list in tqdm.tqdm(train_data_loader):
            batch_count += 1
            print("epoch", epoch, "Running Batch", batch_count)
            for index in range(len(source_list)):
                optim.zero_grad()
                source = source_list[index]
                target = target_list[index]
                source_size = len(source.split())
                if source_size > mx:
                    source = source[:, :mx]
                tok_inp = tokenizer.encode(source)
                tok_tar = tokenizer.encode(target)
                tar_ct = 0
                for tar_el in tok_tar:
                    inp_tensor = torch.tensor([tok_inp])
                    # print('inp tensor size', inp_tensor.size())
                    # print('inp tensor', inp_tensor)
                    tar = torch.tensor(tar_el)
                    if device == 'cuda':
                        inp_tensor = inp_tensor.to('cuda')
                        tar = tar.to('cuda')
                    output = model(inp_tensor)
                    pred = output[0][0][-1]
                    pred_prob = F.softmax(pred)
                    # print("Tar count", tar_ct)
                    loss = F.nll_loss(torch.log(pred_prob).unsqueeze(0), tar.unsqueeze(0))
                    training_loss += loss
                    loss.backward()
                    # clip gradients vector length if > 1 to 1
                    if arg.gradient_clipping > 0.0:
                        nn.utils.clip_grad_norm_(model.parameters(), arg.gradient_clipping)
                    optim.step()
                    sched.step()
                    pred_idx = top_p_sampling(pred_prob, p=arg.top_p)
                    tok_inp.append(tar_el)
                    seen += inp_tensor.size(0)

                # print("Source Given: ", source)
                # predicted_text = tokenizer.decode(tok_inp)
                # print("Predicted: ", predicted_text)
                # print("Target: ", target)

        print("epoch", epoch, "training_loss", training_loss)
        training_loss_list.append(training_loss)

        with torch.no_grad():
            model.eval()
            batch_count = 0
            validation_loss = 0
            for source_list, target_list in tqdm.tqdm(validation_data_loader):
                batch_count += 1
                print("epoch", epoch, "Running Batch", batch_count)
                for index in range(len(source_list)):
                    optim.zero_grad()
                    source = source_list[index]
                    target = target_list[index]
                    source_size = len(source.split())
                    if source_size > mx:
                        source = source[:, :mx]
                    tok_inp = tokenizer.encode(source)
                    tok_tar = tokenizer.encode(target)
                    tar_ct = 0
                    for tar in tok_tar:
                        inp_tensor = torch.tensor([tok_inp])
                        # print('inp tensor size', inp_tensor.size())
                        # print('inp tensor', inp_tensor)
                        tar = torch.tensor(tar)
                        if device == 'cuda':
                            inp_tensor = inp_tensor.to('cuda')
                            tar = tar.to('cuda')
                        output = model(inp_tensor)
                        pred = output[0][0][-1]
                        pred_prob = F.softmax(pred)
                        # print("Tar count", tar_ct)
                        loss = F.nll_loss(torch.log(pred_prob).unsqueeze(0), tar.unsqueeze(0))
                        validation_loss += loss
                        pred_idx = top_p_sampling(pred_prob, p=arg.top_p)
                        tok_inp.append(pred_idx)
                        seen += inp_tensor.size(0)
                        batch_count += 1
                        print("epoch", epoch, "Running Batch", batch_count)

                    print("Source Given: ", source)
                    predicted_text = tokenizer.decode(tok_inp)
                    print("Predicted: ", predicted_text)
                    print("Target: ", target)

            sched.step()
            print("epoch", epoch, "validation_loss", validation_loss)
            validation_loss_list.append(validation_loss)

    model_file = 'saved_model.pkl'
    torch.save(model, model_file)

    plt.figure(figsize = (10, 4))
    plt.subplot(1, 2, 1)
    plt.plot(validation_loss_list, 'bo-', label = 'val-loss')
    plt.plot(training_loss_list, 'ro-', label = 'train-loss')
    plt.grid('on')
    plt.ylabel('loss')
    plt.xlabel('epoch')
    plt.legend(['validation', 'training'], loc='upper right')
    plt.savefig("Loss_vs_epoch.png")

if __name__ == '__main__':
    parser = ArgumentParser()

    """
    Arguments:
        --num-epochs,   -e  Number of epochs
        --batch-size,   -b  Batch size
        --learn-rate,   -l  Learning rate
        --tb_dir,       -T  Tensorboard logging directory 
        --final,        -f  Whether to run on the real test set (if not included, validation set is used)
        --max_pool,         Use max pooling in final classification layer
        --embedding     -E  Size of character embeddings
        --vocab-size    -V  Vocabulary size
        --max           -M  Max sequence length. Longer sequences are clipped (-1 for no limit)
        --heads         -H  Number of attention heads
        --depth         -d  Depth of the network (num of self-attention layers)
        --random-seed   -r  RNG seed
        --lr-warmup         Learning rate warmup
        --gradient-clipping Gradient clipping
        --dropout       -D  Dropout
    """

    parser.add_argument("-e", "--num-epochs",
                        dest="num_epochs",
                        help="Number of epochs.",
                        default=2, type=int)

    parser.add_argument("-b", "--batch-size",
                        dest="batch_size",
                        help="The batch size.",
                        default=4, type=int)

    parser.add_argument("-l", "--learn-rate",
                        dest="lr",
                        help="Learning rate",
                        default=0.0001, type=float)

    parser.add_argument("-T", "--tb_dir", dest="tb_dir",
                        help="Tensorboard logging directory",
                        default='./runs')

    parser.add_argument("-f", "--final", dest="final",
                        help="Whether to run on the real test set (if not included, the validation set is used).",
                        action="store_true")

    parser.add_argument("--max-pool", dest="max_pool",
                        help="Use max pooling in the final classification layer.",
                        action="store_true")

    parser.add_argument("-E", "--embedding", dest="embedding_size",
                        help="Size of the character embeddings.",
                        default=128, type=int)

    parser.add_argument("-V", "--vocab-size", dest="vocab_size",
                        help="Number of words in the vocabulary.",
                        default=50_000, type=int)

    parser.add_argument("-M", "--max", dest="max_length",
                        help="Max sequence length. Longer sequences are clipped (-1 for no limit).",
                        default=512, type=int)

    parser.add_argument("-H", "--heads", dest="num_heads",
                        help="Number of attention heads.",
                        default=8, type=int)

    parser.add_argument("-d", "--depth", dest="depth",
                        help="Depth of the network (nr. of self-attention layers)",
                        default=6, type=int)

    parser.add_argument("-r", "--random-seed",
                        dest="seed",
                        help="RNG seed. Negative for random",
                        default=1, type=int)

    parser.add_argument("--lr-warmup",
                        dest="lr_warmup",
                        help="Learning rate warmup.",
                        default=10_000, type=int)

    parser.add_argument("--gradient-clipping",
                        dest="gradient_clipping",
                        help="Gradient clipping.",
                        default=1.0, type=float)

    parser.add_argument("-D", "--dropout",
                        dest="dropout",
                        help="Dropout rate.",
                        default=0.0, type=float)

    parser.add_argument("-p", "--top-p",
                        dest="top_p",
                        help="Top P sampling.",
                        default=0.9, type=float)

    options = parser.parse_args()
    print('OPTIONS', options)

    main(options)