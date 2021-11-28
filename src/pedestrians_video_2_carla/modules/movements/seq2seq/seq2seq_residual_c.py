from typing import Tuple
import torch
from .seq2seq_embeddings import Seq2SeqEmbeddings
from pytorch3d.transforms.rotation_conversions import matrix_to_rotation_6d, rotation_6d_to_matrix


class Seq2SeqResidualC(Seq2SeqEmbeddings):
    """
    Sequence to sequence model with embeddings and residual connections version C.
    This version uses the residual part in next-frame input, but returns "pure" output.

    The difference from B is that the residual part is multiplied with the input,
    taking advantage our knowledge that we expect multiplicative rotation changes.

    Based on the code from [Sequence to Sequence Learning with Neural Networks](https://github.com/bentrevett/pytorch-seq2seq/blob/master/1%20-%20Sequence%20to%20Sequence%20Learning%20with%20Neural%20Networks.ipynb)
    by [Ben Trevett](https://github.com/bentrevett) licensed under [MIT License](https://github.com/bentrevett/pytorch-seq2seq/blob/master/LICENSE),
    which itself is an implementation of the paper https://arxiv.org/abs/1409.3215:

    ```bibtex
    @misc{sutskever2014sequence,
        title={Sequence to Sequence Learning with Neural Networks}, 
        author={Ilya Sutskever and Oriol Vinyals and Quoc V. Le},
        year={2014},
        eprint={1409.3215},
        archivePrefix={arXiv},
        primaryClass={cs.CL}
    }
    ```
    """

    def _decode_frame(self,
                      hidden: torch.Tensor,
                      cell: torch.Tensor,
                      input: torch.Tensor,
                      needs_forcing: bool,
                      force_indices: torch.Tensor,
                      target_pose_changes: torch.Tensor
                      ) -> Tuple[torch.Tensor, torch.Tensor]:
        bs = input.shape[0]

        output, hidden, cell = self.decoder(input, hidden, cell)
        residual_output = matrix_to_rotation_6d(
            torch.bmm(rotation_6d_to_matrix(input.view((-1, 6))),
                      rotation_6d_to_matrix(output.view((-1, 6))))
        ).view((bs, -1))

        force_input = input[force_indices]
        input = residual_output

        if needs_forcing:
            force_shape = force_input.shape
            input[force_indices] = matrix_to_rotation_6d(
                torch.bmm(rotation_6d_to_matrix(force_input.view((-1, 6))),
                          rotation_6d_to_matrix(target_pose_changes.view((-1, 6))))
            ).view(force_shape)

        return input, output
