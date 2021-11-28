from typing import Tuple
import torch
from .seq2seq_embeddings import Seq2SeqEmbeddings


class Seq2SeqResidualB(Seq2SeqEmbeddings):
    """
    Sequence to sequence model with embeddings and residual connections version B.
    This version uses the residual part in next-frame input, but returns "pure" output.

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
        # insert input token embedding, previous hidden and previous cell states
        # receive output tensor (predictions) and new hidden and cell states
        output, hidden, cell = self.decoder(input, hidden, cell)
        residual_output = output + input

        force_input = input[force_indices]
        input = residual_output

        if needs_forcing:
            input[force_indices] = target_pose_changes + force_input

        return input, output
