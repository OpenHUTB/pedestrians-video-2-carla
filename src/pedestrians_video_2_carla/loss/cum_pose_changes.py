from typing import Dict

import torch
from pytorch3d.transforms.rotation_conversions import euler_angles_to_matrix
from torch import Tensor
from torch.nn.modules import loss


def calculate_loss_cum_pose_changes(criterion: loss._Loss, pose_inputs: Tensor, targets: Dict[str, Tensor], **kwargs) -> Tensor:
    """
    Calculates the loss by comparing the pose changes accumulated over the frames.

    :param criterion: Criterion to use for the loss calculation, e.g. nn.MSELoss().
    :type criterion: _Loss
    :param pose_inputs: The pose changes to compare with the target pose changes.
    :type pose_inputs: Tensor
    :param targets: Dictionary returned from dataset that containins the target pose changes.
    :type targets: Dict[str, Tensor]
    :return: Calculated loss.
    :rtype: Tensor
    """
    # calculate cumulative rotations
    (batch_size, clip_length, bones, *_) = pose_inputs.shape

    cumulative_changes = []
    cumulative_targets = []

    prev_changes = torch.eye(3, device=pose_inputs.device).reshape(
        (1, 3, 3)).repeat((batch_size*bones, 1, 1))
    prev_targets = torch.eye(3, device=pose_inputs.device).reshape(
        (1, 3, 3)).repeat((batch_size*bones, 1, 1))

    matrix_pose_changes = pose_inputs.transpose(0, 1).reshape((clip_length, -1, 3, 3))
    matrix_targets = targets['pose_changes'].transpose(
        0, 1).reshape((clip_length, -1, 3, 3))

    for i in range(clip_length):
        prev_changes = torch.bmm(
            prev_changes,
            matrix_pose_changes[i]
        )
        prev_targets = torch.bmm(
            prev_targets,
            matrix_targets[i]
        )
        cumulative_changes.append(prev_changes)
        cumulative_targets.append(prev_targets)

    loss = criterion(
        torch.stack(cumulative_changes, dim=0).reshape((clip_length, batch_size, bones, 3, 3)).transpose(
            0, 1),
        torch.stack(cumulative_targets, dim=0).reshape((clip_length, batch_size, bones, 3, 3)).transpose(
            0, 1),
    )

    return loss
