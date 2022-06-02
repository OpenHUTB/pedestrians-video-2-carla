import logging
from pedestrians_video_2_carla.data.mixed.mixed_datamodule import MixedDataModule
from pedestrians_video_2_carla.data.openpose.jaad_openpose_datamodule import JAADOpenPoseDataModule
from pedestrians_video_2_carla.data.carla.carla_recorded_datamodule import CarlaRecordedDataModule
from pedestrians_video_2_carla.data.openpose.skeleton import BODY_25_SKELETON
from pedestrians_video_2_carla.data.carla.skeleton import CARLA_SKELETON
from pedestrians_video_2_carla.utils.argparse import flat_args_as_list_arg


class JAADCarlaRecDataModule(MixedDataModule):
    data_modules = [
        JAADOpenPoseDataModule,
        CarlaRecordedDataModule,
    ]
    # default mixing proportions
    train_proportions = [0.2, 0.8]
    val_proportions = [0, -1]
    test_proportions = [0, -1]

    def __init__(self, **kwargs):
        jaad_missing_joint_probabilities = flat_args_as_list_arg(kwargs, 'missing_joint_probabilities', True)
        
        strong_points = kwargs.get('strong_points', 0)
        jaad_noise = kwargs.get('noise', 'zero')
        carla_noise = jaad_noise

        carla_missing_joint_probabilities = MixedDataModule._map_missing_joint_probabilities(
            jaad_missing_joint_probabilities,
            BODY_25_SKELETON,
            CARLA_SKELETON
        )

        if (len(jaad_missing_joint_probabilities) or jaad_noise != 'zero') and strong_points < 1:
            logging.getLogger(__name__).warn(
                'Strong points is less than 1, but JAAD missing joint probabilities and/or noise are set. I\'m going to assume you want to introduce artificial missing joints and noise to datasets OTHER than JAAD.'
            )
            jaad_missing_joint_probabilities = []
            jaad_noise = 'zero'

        super().__init__(
            data_modules_kwargs={
                JAADOpenPoseDataModule: {
                    'data_nodes': BODY_25_SKELETON,
                    'input_nodes': CARLA_SKELETON,
                    'missing_joint_probabilities': jaad_missing_joint_probabilities,
                    'noise': jaad_noise,
                },
                CarlaRecordedDataModule: {
                    'data_nodes': CARLA_SKELETON,
                    'input_nodes': CARLA_SKELETON,
                    'missing_joint_probabilities': carla_missing_joint_probabilities,
                    'noise': carla_noise,
                }
            },
            mappings={
                'frame.pedestrian.is_crossing': 'cross',
            },
            **kwargs
        )
