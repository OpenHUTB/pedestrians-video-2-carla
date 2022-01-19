from functools import lru_cache
from logging import root
from typing import List, Any, Dict
from human_body_prior.body_model.body_model import BodyModel
from body_visualizer.mesh.mesh_viewer import MeshViewer
import os
import numpy as np
import trimesh
from torch import Tensor

from pedestrians_video_2_carla.renderers.renderer import Renderer
from pedestrians_video_2_carla.data.smpl.utils import get_body_model


class SMPLRenderer(Renderer):
    """
    This renderer basically does the same job as `body_visualizer.tools.vis_tools.render_smpl_params`.
    """

    def __init__(self, color=(0.7, 0.7, 0.7), **kwargs) -> None:
        super().__init__(**kwargs)

        self.color = list(color)
        self.mesh_viewer = MeshViewer(
            width=self._image_size[0], height=self._image_size[1], use_offscreen=True)

    def render(self, body_pose: List[Tensor], meta: List[Dict[str, Any]], **kwargs) -> List[np.ndarray]:
        rendered_videos = len(meta['video_id'])

        for clip_idx in range(rendered_videos):
            video = self.render_clip(
                body_model=get_body_model(
                    gender=meta['gender'][clip_idx],
                    device=body_pose[clip_idx].device
                ),
                body_pose_clip=body_pose[clip_idx]
            )
            yield video

    def render_clip(self, body_model: BodyModel, body_pose_clip: Tensor) -> np.ndarray:
        video = []

        faces = body_model.f.cpu()
        vertices = body_model(
            pose_body=body_pose_clip[:, 3:],
            root_orient=body_pose_clip[:, :3]
        ).v.cpu()
        _, num_verts = vertices.shape[:-1]

        for vert in vertices:
            frame = self.render_frame(vert, faces, num_verts)
            video.append(frame)

        return np.stack(video)

    def render_frame(self, vertices, faces, num_verts) -> np.ndarray:
        mesh = trimesh.base.Trimesh(
            vertices, faces, vertex_colors=num_verts*self.color)
        self.mesh_viewer.set_meshes([mesh], 'static')

        return self.mesh_viewer.render()
