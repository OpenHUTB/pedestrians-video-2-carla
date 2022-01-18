import os
from typing import Optional

import h5py
import numpy as np
import torch
from pedestrians_video_2_carla.data.base.base_datamodule import BaseDataModule
from pedestrians_video_2_carla.data.carla.carla_dataset import (
    CarlaDataset, Carla2D3DIterableDataset)
from tqdm import trange
import math

from pedestrians_video_2_carla.utils.argparse import MinMaxAction


class Carla2D3DDataModule(BaseDataModule):
    def __init__(self,
                 val_set_size: Optional[int] = 8192,
                 test_set_size: Optional[int] = 8192,
                 **kwargs):
        self.val_set_size = val_set_size
        self.test_set_size = test_set_size
        self.kwargs = kwargs

        super().__init__(**kwargs)

    @property
    def settings(self):
        return {
            **super().settings,
            'random_changes_each_frame': self.kwargs.get('random_changes_each_frame'),
            'max_change_in_deg': self.kwargs.get('max_change_in_deg'),
            'max_world_rot_change_in_deg': self.kwargs.get('max_world_rot_change_in_deg'),
            'max_initial_world_rot_change_in_deg': self.kwargs.get('max_initial_world_rot_change_in_deg'),
            'missing_point_probability': self.kwargs.get('missing_point_probability'),
            'val_set_size': self.val_set_size,
            'test_set_size': self.test_set_size,
        }

    @staticmethod
    def add_data_specific_args(parent_parser):
        BaseDataModule.add_data_specific_args(parent_parser)

        parser = parent_parser.add_argument_group("Carla2D3D DataModule")
        parser.add_argument(
            "--random_changes_each_frame",
            type=int,
            default=3,
            metavar='NUM_NODES',
            help="Number of nodes that will be randomly changed in each frame."
        )
        parser.add_argument(
            "--max_change_in_deg",
            type=int,
            default=5,
            minimum=0,
            maximum=15,
            action=MinMaxAction,
            metavar='DEGREES',
            help="Max random [+/-] change in degrees."
        )
        parser.add_argument(
            "--max_world_rot_change_in_deg",
            type=int,
            default=0,
            minimum=0,
            maximum=15,
            action=MinMaxAction,
            metavar='DEGREES',
            help="Max random [+/-] world rotation yaw change in each frame in degrees."
        )
        parser.add_argument(
            "--max_initial_world_rot_change_in_deg",
            type=int,
            default=0,
            minimum=0,
            maximum=180,
            action=MinMaxAction,
            metavar='DEGREES',
            help="Max random [+/-] 'world' rotation yaw change in degrees applied to first frame."
        )
        parser.add_argument(
            "--missing_point_probability",
            type=float,
            default=0.0,
            metavar='PROB',
            help="""
                Probability that a joint/node will be missing ("not detected") in a skeleton in a frame.
                Missing nodes are selected separately for each frame.
            """
        )
        parser.add_argument(
            "--val_set_size",
            type=int,
            default=8192,
            metavar='NUM_SAMPLES',
            help="Number of samples (clips) to use for validation."
        )
        parser.add_argument(
            "--test_set_size",
            type=int,
            default=8192,
            metavar='NUM_SAMPLES',
            help="Number of samples (clips) to use for testing."
        )
        return parent_parser

    def prepare_data(self) -> None:
        if not self._needs_preparation:
            return

        # generate and save validation & test sets so they are reproducible
        iterable_dataset = Carla2D3DIterableDataset(
            nodes=self.nodes,
            **{
                **self.kwargs,
                'transform': None  # we want raw data in dataset
            },
        )

        sizes = [self.val_set_size, self.test_set_size]
        names = ['val', 'test']
        for (size, name) in zip(sizes, names):
            if size <= 0:
                continue

            batches = math.ceil(size / self.batch_size)
            clips_set = tuple(zip(*[iterable_dataset.generate_batch()
                              for _ in trange(batches, desc=f'Generating {name} set')]))
            projection_2d = torch.cat(clips_set[0], dim=0).cpu().numpy()
            targets = {k: [dic[k] for dic in clips_set[1]] for k in clips_set[1][0]}
            meta = {k: [dic[k] for dic in clips_set[2]] for k in clips_set[2][0]}

            with h5py.File(os.path.join(self._subsets_dir, "{}.hdf5".format(name)), "w") as f:
                f.create_dataset("carla_2d_3d/projection_2d", data=projection_2d[:size],
                                 chunks=(1, *projection_2d.shape[1:]))

                for k, v in targets.items():
                    stacked_v = np.concatenate(v, axis=0)
                    f.create_dataset(f"carla_2d_3d/targets/{k}", data=stacked_v[:size],
                                     chunks=(1, *stacked_v.shape[1:]))

                for k, v in meta.items():
                    stacked_v = np.concatenate(v, axis=0)
                    unique = list(set(stacked_v))
                    labels = np.array([
                        s.encode("latin-1") for s in unique
                    ], dtype=h5py.string_dtype('ascii', 30))
                    mapping = {s: i for i, s in enumerate(unique)}
                    f.create_dataset("carla_2d_3d/meta/{}".format(k),
                                     data=[mapping[s] for s in stacked_v[:size]], dtype=np.uint16)
                    f["carla_2d_3d/meta/{}".format(k)].attrs["labels"] = labels

        # save settings
        self.save_settings()

    def setup(self, stage: Optional[str] = None) -> None:
        if stage == "fit" or stage is None:
            self.train_set = Carla2D3DIterableDataset(
                nodes=self.nodes,
                transform=self.transform,
                **self.kwargs,
            )
            self.val_set = CarlaDataset(
                os.path.join(self._subsets_dir, 'val.hdf5'),
                nodes=self.nodes,
                transform=self.transform
            )

        if stage == "test" or stage is None:
            self.test_set = CarlaDataset(
                os.path.join(self._subsets_dir, 'test.hdf5'),
                nodes=self.nodes,
                transform=self.transform
            )

    def train_dataloader(self):
        # no need to shuffle, it is randomly generated
        return self._dataloader(self.train_set)
