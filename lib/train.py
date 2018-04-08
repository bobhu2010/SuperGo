import torch
import numpy as np
import pickle
import time
import torch.nn.functional as F
import multiprocessing
import multiprocessing.pool
from .process import MyPool
from copy import deepcopy
from pymongo import MongoClient
from torch.autograd import Variable
from const import *
from models.agent import Player
from .dataset import SelfPlayDataset
from torch.utils.data import DataLoader
from .evaluate import evaluate


class AlphaLoss(torch.nn.Module):
    """ Custom loss as defined in the paper """

    def __init__(self):
        super(AlphaLoss, self).__init__()

    def forward(self, winner, self_play_winner, probas, self_play_probas):
        value_error = F.mse_loss(winner, self_play_winner)
        if NO_MCTS:
            policy_error = F.binary_cross_entropy(probas, self_play_probas)
        else:
            policy_error = F.cross_entropy(probas, self_play_probas)
        return value_error + policy_error


def fetch_new_games(collection, dataset, last_id):
    """ Update the dataset with new games from the databse """

    new_games = collection.find({"id": {"$gt": last_id}})
    z = new_games.count()
    ## No new game 
    if z == 0:
        return last_id
    print("[TRAIN] Fetching: %d" % z)
    for game in new_games:
        print("cc")
        dataset.update(pickle.loads(game['game']))
        last_id += 1
    return last_id


def train_epoch(player, optimizer, example, criterion):
    """ Used to train the 3 models over a single batch """

    optimizer.zero_grad()

    feature_maps = player.extractor(example['state'])
    winner = player.value_net(feature_maps)
    probas = player.policy_net(feature_maps)

    loss = criterion(winner.view(-1), example['winner'], probas, example['move'])
    loss.backward()
    optimizer.step()

    return loss



def new_agent(result):
    print("[TRAIN RESULT !!!] ", player)
    print("[TRAIN RESULT !!!] ", result)
    if result:
        player = new_player


def train(current_time):
    """ Train the models using the data generated by the self-play """

    last_id = 0
    ite = 1
    improvements = 1
    update = True
    criterion = AlphaLoss()
    dataset = SelfPlayDataset()
    
    ## Database connection
    client = MongoClient()
    collection = client.superGo[current_time]

    ## First player
    player = Player()
    player.save_models(improvements, current_time)

    while len(dataset) < MOVES:
        last_id = fetch_new_games(collection, dataset, last_id)
        if last_id != 0:
            break
        time.sleep(10)

    dataloader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)
    while True:
        if update:
            player.save_models(improvements, current_time)
            new_player = deepcopy(player)
            joint_params = list(new_player.extractor.parameters()) + \
                        list(new_player.policy_net.parameters()) +\
                        list(new_player.value_net.parameters())
            optimizer = torch.optim.SGD(joint_params, lr=LR, \
                                            weight_decay=L2_REG, momentum=MOMENTUM)
            update = False
    
        for batch_idx, (state, move, winner) in enumerate(dataloader):
            if ite % TRAIN_STEPS == 0:
                player = new_player
                improvements += 1
                update = True
                # pool = MyPool(1)
                # x = pool.apply_async(evaluate, args=(player, new_player,), \
                #         callback=new_agent)
                # x.get()
                # pool.close()
                # pool.join()

            example = {
                'state': Variable(state).type(DTYPE_FLOAT),
                'winner': Variable(winner).type(DTYPE_FLOAT),
                'move' : Variable(move).type(DTYPE_FLOAT if NO_MCTS else DTYPE_LONG)
            }
            loss = train_epoch(new_player, optimizer, example, criterion)
            print("[TRAIN] batch index: %d loss: %.3f" \
                    % (batch_idx / 10, loss))
            ite += 1
        
        last_id = fetch_new_games(collection, dataset, last_id)
    