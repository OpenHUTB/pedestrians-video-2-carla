from typing import Tuple, Union
from pedestrians_video_2_carla.modules.base.output_types import MovementsModelOutputType, TrajectoryModelOutputType


from pedestrians_video_2_carla.skeletons.nodes.carla import CarlaHipsNeckExtractor
from pedestrians_video_2_carla.transforms.hips_neck import HipsNeckNormalize
from pedestrians_video_2_carla.transforms.reference_skeletons import ReferenceSkeletonsDenormalize
from pedestrians_video_2_carla.walker_control.controlled_pedestrian import \
    ControlledPedestrian
from pedestrians_video_2_carla.walker_control.torch.pose import P3dPose
from pedestrians_video_2_carla.walker_control.torch.pose_projection import \
    P3dPoseProjection
from pedestrians_video_2_carla.walker_control.torch.world import calculate_world_from_changes

import torch
from torch import nn
from torch.functional import Tensor


class ProjectionModule(nn.Module):
    def __init__(self,
                 projection_transform=None,
                 movements_output_type: MovementsModelOutputType = MovementsModelOutputType.pose_changes,
                 trajectory_output_type: TrajectoryModelOutputType = TrajectoryModelOutputType.changes,
                 **kwargs
                 ) -> None:
        super().__init__()

        if projection_transform is None:
            projection_transform = HipsNeckNormalize(CarlaHipsNeckExtractor())
        self.projection_transform = projection_transform

        self.movements_output_type = movements_output_type
        self.trajectory_output_type = trajectory_output_type

        if self.movements_output_type == MovementsModelOutputType.pose_changes:
            self.__calculate_abs = self._calculate_abs_from_pose_changes
        elif self.movements_output_type == MovementsModelOutputType.absolute_loc or self.movements_output_type == MovementsModelOutputType.absolute_loc_rot:
            self.__denormalize = ReferenceSkeletonsDenormalize(
                autonormalize=True
            )
            if self.movements_output_type == MovementsModelOutputType.absolute_loc:
                self.__calculate_abs = self._calculate_abs_from_abs_loc_output
            else:
                self.__calculate_abs = self._calculate_abs_from_abs_loc_rot_output
        elif self.movements_output_type == MovementsModelOutputType.relative_rot:
            self.__calculate_abs = self._calculate_abs_from_relative_rot

        if self.trajectory_output_type == TrajectoryModelOutputType.changes:
            self.__calculate_world = self._calculate_world_from_changes
        elif self.trajectory_output_type == TrajectoryModelOutputType.loc_rot:
            self.__calculate_world = self._calculate_world_from_loc_rot

        # set on every batch
        self.__pedestrians = None
        self.__pose_projection = None
        self.__world_locations = None
        self.__world_rotations = None

    def on_batch_start(self, batch, batch_idx):
        (frames, _, meta) = batch
        batch_size = len(frames)

        # create pedestrian object for each clip in batch
        self.__pedestrians = [
            ControlledPedestrian(world=None, age=meta['age'][idx], gender=meta['gender'][idx],
                                 pose_cls=P3dPose, device=frames.device,
                                 reference_pose=meta['reference_pose'][idx] if 'reference_pose' in meta else None)
            for idx in range(batch_size)
        ]
        # only create one - we're assuming that camera is setup in the same for way for each pedestrian
        self.__pose_projection = P3dPoseProjection(
            device=frames.device, pedestrian=self.__pedestrians[0])

        # TODO: handle initial world transform matching instead of setting all zeros
        self.__world_locations = torch.zeros(
            (batch_size, 3), device=frames.device)
        self.__world_rotations = torch.eye(3, device=frames.device).reshape(
            (1, 3, 3)).repeat((batch_size, 1, 1))

    def project_pose(self, pose_inputs_batch: Union[Tensor, Tuple[Tensor, Tensor]], world_loc_change_batch: Tensor = None, world_rot_change_batch: Tensor = None) -> Tuple[Tensor, Tensor, Tensor]:
        """
        Handles calculation of the pose projection.

        :param pose_inputs_batch: (N - batch_size, L - clip_length, B - bones, 3, 3 - rotations as rotation matrices) pose changes
            OR (N - batch_size, L - clip_length, B - bones, 3 - x, y, z) absolute pose locations
            OR (N - batch_size, L - clip_length, B - bones, 3 - x, y, z) absolute pose locations + (N - batch_size, L - clip_length, B - bones, 3, 3 - rotation matrix)
        :type pose_inputs_batch: Union[Tensor, Tuple[Tensor, Tensor]]
        :param world_loc_change_batch: (N - batch_size, L - clip_length, 3 - location changes)
        :type world_loc_change_batch: Tensor
        :param world_rot_change_batch: (N - batch_size, L - clip_length, 3, 3 - rotation changes as rotation matrices)
        :type world_rot_change_batch: Tensor
        :raises RuntimeError: when pose_inputs_batch dimensionality is incorrect
        :return: Pose projection, absolute pose locations & absolute pose rotations
        :rtype: Tuple[Tensor, Tensor, Tensor]
        """
        # TODO: switch batch and clip length dimensions?
        if self.movements_output_type == MovementsModelOutputType.pose_changes and pose_inputs_batch.ndim < 5:
            raise RuntimeError(
                'Pose changes should have shape of (N - batch_size, L - clip_length, B - bones, 3, 3 - rotations as rotation matrices)')
        elif self.movements_output_type == MovementsModelOutputType.absolute_loc and pose_inputs_batch.ndim < 4:
            raise RuntimeError(
                'Absolute location should have shape of (N - batch_size, L - clip_length, B - bones, 3 - absolute location coordinates)')
        elif self.movements_output_type == MovementsModelOutputType.absolute_loc_rot and not isinstance(pose_inputs_batch, tuple):
            raise RuntimeError(
                'Absolute location with rotation should be a Tuple of tensors.')

        absolute_loc, absolute_rot = self.__calculate_abs(pose_inputs_batch)
        world_loc, world_rot = self.__calculate_world(
            absolute_loc, world_loc_change_batch, world_rot_change_batch)

        projections = torch.empty_like(absolute_loc)

        # for every frame in clip
        for i in range(absolute_loc.shape[1]):
            projections[:, i] = self.__pose_projection.forward(
                absolute_loc[:, i],
                world_loc[:, i],
                world_rot[:, i]
            )

        return projections, absolute_loc, absolute_rot, world_loc, world_rot

    def _calculate_abs_from_abs_loc_output(self, pose_inputs_batch):
        # if the movements_output_type is absolute_loc, we need to convert it
        # to something that actually scales back to the original skeleton size
        # so self-normalize first, and denormalize with respect to reference pose later
        absolute_loc = self.__denormalize.from_abs(pose_inputs_batch, {
            'age': [p.age for p in self.__pedestrians],
            'gender': [p.gender for p in self.__pedestrians]
        })
        absolute_rot = None
        return absolute_loc, absolute_rot

    def _calculate_abs_from_abs_loc_rot_output(self, pose_inputs_batch):
        absolute_loc, _ = self._calculate_abs_from_abs_loc_output(pose_inputs_batch[0])
        absolute_rot = pose_inputs_batch[1]
        return absolute_loc, absolute_rot

    def _calculate_abs_from_relative_rot(self, pose_inputs_batch):
        (batch_size, clip_length, points, *_) = pose_inputs_batch.shape

        prev_relative_loc, _ = self.get_reference_tensors()

        # ensure dimensions match
        shape_3d = tuple([1, *prev_relative_loc.shape][-3:])
        prev_relative_loc = prev_relative_loc.reshape(shape_3d).repeat(
            (int(batch_size / shape_3d[0]), 1, 1))

        absolute_loc = torch.empty(
            (batch_size, clip_length, points, 3), device=pose_inputs_batch.device)
        absolute_rot = torch.empty(
            (batch_size, clip_length, points, 3, 3), device=pose_inputs_batch.device)

        pose: P3dPose = self.__pedestrians[0].current_pose

        for i in range(clip_length):
            (absolute_loc[:, i], absolute_rot[:, i]) = pose.relative_to_absolute(
                prev_relative_loc, pose_inputs_batch[:, i])

        return absolute_loc, absolute_rot

    def _calculate_abs_from_pose_changes(self, pose_inputs_batch):
        (batch_size, clip_length, points, *_) = pose_inputs_batch.shape

        prev_relative_loc, prev_relative_rot = self.get_reference_tensors()

        # get subsequent poses calculated
        # naively for now
        # TODO: wouldn't it be better if P3dPose and P3PoseProjection were directly sequence-aware?
        # so that we only get in the initial loc/rot and a sequence of changes
        absolute_loc = torch.empty(
            (batch_size, clip_length, points, 3), device=pose_inputs_batch.device)
        absolute_rot = torch.empty(
            (batch_size, clip_length, points, 3, 3), device=pose_inputs_batch.device)

        pose: P3dPose = self.__pedestrians[0].current_pose

        for i in range(clip_length):
            (absolute_loc[:, i], absolute_rot[:, i], prev_relative_rot) = pose.forward(
                pose_inputs_batch[:, i], prev_relative_loc, prev_relative_rot)

        return absolute_loc, absolute_rot

    def get_reference_tensors(self):
        (prev_relative_loc, prev_relative_rot) = zip(*[
            p.current_pose.tensors
            for p in self.__pedestrians
        ])

        prev_relative_loc = torch.stack(prev_relative_loc)
        prev_relative_rot = torch.stack(prev_relative_rot)

        return prev_relative_loc, prev_relative_rot

    def _calculate_world_from_changes(self, absolute_loc: Tensor, world_loc_change_batch: Tensor = None, world_rot_change_batch: Tensor = None):
        return calculate_world_from_changes(
            absolute_loc.shape, absolute_loc.device,
            world_loc_change_batch, world_rot_change_batch,
            self.__world_locations, self.__world_rotations
        )

    def _calculate_world_from_loc_rot(self, absolute_loc: Tensor, world_loc_inputs: Tensor = None, world_rot_inputs: Tensor = None):
        batch_size, clip_length, *_ = absolute_loc.shape

        if world_loc_inputs is None:
            world_loc_inputs = torch.zeros((batch_size, clip_length, 3),
                                           device=absolute_loc.device)  # no world loc change

        if world_rot_inputs is None:
            world_rot_inputs = torch.eye(3, device=absolute_loc.device).reshape(
                (1, 1, 3, 3)).repeat((batch_size, clip_length, 1, 1))  # no world rot change

        return world_loc_inputs, world_rot_inputs

    def forward(self, pose_inputs: Union[Tensor, Tuple[Tensor, Tensor]], world_loc_inputs: Tensor = None, world_rot_inputs: Tensor = None) -> Tuple[Tensor, Tensor, Tensor, Tensor]:
        (projected_pose, absolute_pose_loc, absolute_pose_rot, world_loc, world_rot) = self.project_pose(
            pose_inputs,
            world_loc_inputs,
            world_rot_inputs,
        )
        normalized_projection = self.projection_transform(projected_pose)

        return (projected_pose, normalized_projection, absolute_pose_loc, absolute_pose_rot, world_loc, world_rot)
