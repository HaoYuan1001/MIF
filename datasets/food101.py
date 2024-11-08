import os

from .utils import Datum, DatasetBase, read_json, write_json, build_data_loader
from .oxford_pets import OxfordPets


template = ['a photo of {}, a type of food.']


class Food101(DatasetBase):

    dataset_dir = 'food-101'

    def __init__(self, root, num_shots):
        self.dataset_dir = root
        self.image_dir = os.path.join(self.dataset_dir, 'images')
        self.split_path = os.path.join(self.dataset_dir, 'split_zhou_Food101.json')
        
        self.template = template

        train, val, test = OxfordPets.read_split(self.split_path, self.image_dir)
        train_cache = train.copy()
        train = self.generate_fewshot_dataset(train, num_shots=num_shots)
        # train_cache = self.generate_fewshot_dataset_noise(train_cache, num_shots=num_shots, dataset_name='Food101')

        super().__init__(train_x=train, val=val, test=test, train_cache = train_cache)