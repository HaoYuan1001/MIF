import os
import argparse
import yaml

import torch
import torchvision.transforms as transforms
import clip
from logger import *
from trainer import Trainer
from datasets import build_dataset
from datasets.utils import _transform, build_data_loader
from utils import *
from RandAugment import RandAugment


def get_arguments():
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', dest='config', help='settings in yaml format')
    parser.add_argument('--shots', default=16, type=int, help='number of shots for each class in training')
    # parser.add_argument('--train_epoch', default=100, type=int, help='number of epochs to train the model')
    parser.add_argument('--title', type=str, default='default_title', help='title of this training')
    parser.add_argument('--lr', default=1e-3, type=float, help='learning_rate')
    parser.add_argument('--log_file', default='log', type=str, help='log file')
    parser.add_argument('--desc', default='default description', type=str, help='more details and description of this training')
    parser.add_argument('--backbone', type=str, choices=['RN50', 'RN101', 'ViT-B/32', 'ViT-B/16'], default='RN50', help='backbone of the visual endoer')
    parser.add_argument('--seed', default=1, type=int, help='seed for the whole training')
    parser.add_argument('--delta', default=1, type=float, help='weight for the -kl loss')
    parser.add_argument('--gammar', default=1, type=float, help='weight for the l1 loss')
    parser.add_argument('--augment_epoch',default=10, type=int, help='augment_epoch')



    args = parser.parse_args()
    
    assert (os.path.exists(args.config))
    cfg = yaml.load(open(args.config, 'r'), Loader=yaml.Loader)
    for arg in vars(args):
        cfg[arg] = getattr(args, arg)
    torch.set_num_threads(cfg['num_threads'])

    return cfg

def get_dalle_shots(cfg):
    # 定义dalle_shots数组
    dalle_shots = cfg['dalle_shots']  # shots的对应值
    shots = cfg['shots']
    # 根据输入的shots选择对应的dalle_shots元素
    if shots == 1:
        return dalle_shots[0]
    elif shots == 2:
        return dalle_shots[1]
    elif shots == 4:
        return dalle_shots[2]
    elif shots == 8:
        return dalle_shots[3]
    elif shots == 16:
        return dalle_shots[4]
    else:
        return None  # 如果shots不在1,2,4,8,16范围内



def main():

    # Load config file
    cfg = get_arguments()
    setup_seed(cfg['seed'])
    
    # CLIP: download clip model to ./model/clip
    clip_model, preprocess = clip.load(cfg['backbone'], download_root='./model/clip', num_classes=cfg['num_classes'])
    clip_model.eval()
    
    # Get dataset and dataloader
    print(f"Preparing {cfg['dataset']} dataset.")


    cache_train_transform = _transform(224, True)
    train_transform = transforms.Compose([
        transforms.RandomResizedCrop(size=224, scale=(0.5, 1), interpolation=transforms.InterpolationMode.BICUBIC),
        # ImageNetPolicy(),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.48145466, 0.4578275, 0.40821073), std=(0.26862954, 0.26130258, 0.27577711))
    ])


    # Add RandAugment with N, M(hyperparameter，N控制增加数据增强的数量，M控制数据增强强度，m取值范围为[0,30])
    cache_train_transform.transforms.insert(0, RandAugment(1, 5))
    dataset = build_dataset(cfg['dataset'], cfg['data_path'], cfg['shots'])
    dalle_shots = get_dalle_shots(cfg)
    dalle_dataset = build_dataset(cfg['dalle_dataset'], cfg['root_path'], dalle_shots)

    train_loader_cache = build_data_loader(data_source=dalle_dataset.train_x, batch_size=cfg['batch_size'], tfm=cache_train_transform, is_train=True, shuffle=False)


    train_loader = build_data_loader(data_source=dataset.train_x, batch_size=cfg['batch_size'], tfm=train_transform, is_train=True, shuffle=True)

    val_loader = build_data_loader(data_source=dataset.val, batch_size=64, is_train=False, tfm=preprocess, shuffle=False)
    test_loader = build_data_loader(data_source=dataset.test, batch_size=64, is_train=False, tfm=preprocess, shuffle=False)
    
    # Show config
    assert cfg['num_classes'] == len(dataset.classnames)
    print("\nRunning configs.")
    print(cfg, "\n")
    
    # Initialize diretory and logger
    safe_backbone = cfg['backbone'].replace('/', '_')
    dir_name = f"s{cfg['shots']}_{cfg['dataset']}_{safe_backbone}"
    checkpoint_dir = f'./checkpoint/{dir_name}'
    cfg['checkpoint_dir'] = checkpoint_dir
    log_dir = f'./log/{dir_name}'
    make_dirs(checkpoint_dir, log_dir)
    setup_logging(save_dir=log_dir, file_name=cfg['log_file'])
    logger = logging.getLogger(name=cfg['title'])
    # log_init(logger, cfg)    
    with open(cfg['gpt3_prompt_file']) as f:
        gpt3_prompt = json.load(f)

    # Load cached textual weights W
    print("Getting cached textual weights W ...")
    feat_path = os.path.join(cfg['cache_dir'], f"{cfg['dataset']}_{safe_backbone}_textfeats.pt")
    if cfg['gpt3_prompt']:
        text_feats = gpt_clip_classifier(dataset.classnames, gpt3_prompt, clip_model, dataset.template)
    else:
        text_feats = clip_classifier(feat_path, dataset.classnames, dataset.template, clip_model)

    # Preparation for training
    for param in clip_model.parameters():
        param.requires_grad = False
    for name, param in clip_model.named_parameters():
        if 'adapter' in name:
            param.requires_grad = True

    # Construct the cache model by few-shot training set
    print("\nConstructing cache model by few-shot visual features and labels.")
    cache_keys, cache_values = build_cache_model(cfg, clip_model, train_loader_cache)

    # Pre-load val features
    print("\nLoading visual features and labels from val set.")
    val_features, val_labels = pre_load_features(cfg, "val", clip_model, val_loader)

    # Pre-load test features
    print("\nLoading visual features and labels from test set.")
    test_features, test_labels = pre_load_features(cfg, "test", clip_model, test_loader)

    trainer = Trainer(cfg, clip_model, train_loader, test_loader, logger, text_feats, cache_keys, cache_values, val_features, val_labels, test_features, test_labels,val_loader )
    trainer.train()


if __name__ == '__main__':
    main()