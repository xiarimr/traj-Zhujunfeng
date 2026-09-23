"""Grid-based pooling variant that sums features sharing a grid cell."""
import torch

from .gridbased_pooling import GridBasedPooling


class SumGridBasedPooling(GridBasedPooling):
    """Use elementwise sum when several neighbours occupy the same cell."""

    def occupancy(self, obs, other_values=None, past_obs=None):
        del past_obs
        batch_size = obs.size(0)
        num_tracks = obs.size(1)
        obs_for_grid = obs.clone()
        obs_for_grid[torch.isnan(obs_for_grid).any(dim=-1)] = -500.0
        grid_side = self.n * self.pool_size
        num_cells = grid_side ** 2
        if num_tracks == 1:
            return self.constant * torch.ones(
                1, self.pooling_dim, self.n, self.n, device=obs.device
            )

        unfolded = obs_for_grid.unsqueeze(1).repeat(1, num_tracks, 1, 1)
        relative = unfolded - obs_for_grid.unsqueeze(2)
        not_self = ~torch.eye(num_tracks, device=obs.device, dtype=torch.bool)
        not_self = not_self.unsqueeze(0).repeat(batch_size, 1, 1)
        relative = relative[not_self].reshape(
            batch_size, num_tracks, num_tracks - 1, 2
        )
        if other_values is None:
            other_values = torch.ones(
                batch_size, num_tracks, num_tracks - 1, self.pooling_dim,
                device=obs.device,
            )

        if self.front:
            offset = torch.tensor(
                [grid_side / 2, 0], device=obs.device, dtype=relative.dtype
            )
            grid_xy = relative / (self.cell_side / self.pool_size) + offset
        else:
            grid_xy = relative / (self.cell_side / self.pool_size) + grid_side / 2

        in_range = ((grid_xy >= 0) & (grid_xy < grid_side)).all(dim=-1)
        safe_xy = torch.where(
            in_range.unsqueeze(-1), grid_xy, torch.zeros_like(grid_xy)
        )
        cell_index = safe_xy[..., 0].long() * grid_side + safe_xy[..., 1].long()
        rows = batch_size * num_tracks
        neighbours = num_tracks - 1
        cell_index = cell_index.reshape(rows, neighbours)
        values = other_values.reshape(rows, neighbours, -1)
        values = values * in_range.reshape(rows, neighbours, 1).to(values.dtype)

        expanded_index = cell_index.unsqueeze(-1).expand(-1, -1, values.size(-1))
        occ = torch.zeros(
            rows, num_cells, self.pooling_dim,
            device=obs.device, dtype=values.dtype,
        ).scatter_add(1, expanded_index, values)

        if self.constant != 0:
            counts = torch.zeros(rows, num_cells, device=obs.device).scatter_add(
                1, cell_index,
                in_range.reshape(rows, neighbours).to(values.dtype),
            )
            occ = torch.where(
                counts.unsqueeze(-1) > 0, occ,
                torch.full_like(occ, self.constant),
            )

        occ_2d = occ.transpose(1, 2).reshape(rows, -1, grid_side, grid_side)
        if self.blur_size == 1:
            occ_blurred = occ_2d
        else:
            occ_blurred = torch.nn.functional.avg_pool2d(
                occ_2d, self.blur_size, 1, int(self.blur_size / 2),
                count_include_pad=True,
            )
        return torch.nn.functional.lp_pool2d(occ_blurred, 1, self.pool_size)
