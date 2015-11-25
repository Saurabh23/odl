# Copyright 2014, 2015 The ODL development group
#
# This file is part of ODL.
#
# ODL is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ODL is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ODL.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import print_function, division, absolute_import
from future import standard_library
standard_library.install_aliases()

# External
import numpy as np
import pytest
# ODL
from odl import (Interval, Rectangle, Cuboid, FunctionSpace,
                 uniform_sampling, uniform_discr)
from odl.util.testutils import all_equal, is_subdict
# TomODL
from odltomo import ASTRA_AVAILABLE
from odltomo import (Parallel2dGeometry, FanFlatGeometry,
    Parallel3dGeometry, CircularConeFlatGeometry, HelicalConeFlatGeometry)
from odltomo.backends.astra_cuda import astra_gpu_forward_projector_call
from odltomo.util.testutils import skip_if_no_astra

# if ASTRA_AVAILABLE:
#     import astra
# else:
#     astra = None


# TODO: test other interpolations once implemented
@skip_if_no_astra
def test_astra_gpu_projector_call_2d():

    # DiscreteLp element
    vol_space = FunctionSpace(Rectangle([-1, -1.1], [1, 1.1]))
    nvoxels = (50, 55)
    discr_vol_space = uniform_discr(vol_space, nvoxels, dtype='float32')
    discr_data = discr_vol_space.element(1)

    # motion and detector parameters, and geometry
    angle_offset = 0
    angle_intvl = Interval(0, 2 * np.pi)
    angle_grid = uniform_sampling(angle_intvl, 36, as_midp=False)
    dparams = Interval(-2, 2)
    det_grid = uniform_sampling(dparams, 40)
    geom_p2d = Parallel2dGeometry(angle_intvl, dparams, angle_grid, det_grid)
    src_rad = 1000
    det_rad = 100
    geom_ff = FanFlatGeometry(angle_intvl, dparams, src_rad, det_rad,
                              angle_grid, det_grid, angle_offset)

    # DiscreteLp
    ind = 1
    proj_rect = angle_intvl.insert(dparams, ind)
    proj_space = FunctionSpace(proj_rect)
    # TODO: question: intervals have default index, grids not
    npixels = angle_grid.insert(det_grid, ind).shape
    discr_proj_space = uniform_discr(proj_space, npixels, dtype='float32')

    print('\n\n angle interval:', angle_intvl, '\n det params:', dparams,
          '\n proj rectangle:', proj_rect)
    print(' vol data:', discr_data.shape,
          np.min(discr_data), np.max(discr_data), np.mean(discr_data),
          discr_vol_space.interp)

    save_dir = '/home/jmoosmann/Documents/astra_odl/forward/'
    proj_data = astra_gpu_forward_projector_call(discr_data, geom_p2d,
                                                 discr_proj_space)

    print(' p2d proj:', proj_data.shape, np.min(proj_data), np.max(
        proj_data), np.mean(proj_data), discr_proj_space.interp)
    proj_data.show('imshow', saveto=save_dir+'parallel2d_cuda.png')


    proj_data = astra_gpu_forward_projector_call(discr_data, geom_ff,
                                                 discr_proj_space)

    print('  ff proj:', proj_data.shape, np.min(proj_data), np.max(
        proj_data), np.mean(proj_data), discr_proj_space.interp)
    proj_data.show('imshow', saveto=save_dir+'fanflat_cuda.png')


@skip_if_no_astra
def test_astra_gpu_projector_call_3d():

    # DiscreteLp element
    vol_space = FunctionSpace(Cuboid([-1, -1.1, -0.8], [1, 1.1, 0.8]))
    nvoxels = (50, 55, 40)
    discr_vol_space = uniform_discr(vol_space, nvoxels, dtype='float32')
    discr_data = discr_vol_space.element(1)

    # motion and detector parameters, and geometry
    angle_offset = 0
    angle_intvl = Interval(0, 2 * np.pi)
    angle_grid = uniform_sampling(angle_intvl, 36, as_midp=False)
    dparams = Rectangle([-2, -1.5], [2, 1.5])
    det_grid = uniform_sampling(dparams, (40, 30))
    geom_p3d = Parallel3dGeometry(angle_intvl, dparams, angle_grid, det_grid)
    src_rad = 1000
    det_rad = 100
    geom_ccf = CircularConeFlatGeometry(angle_intvl, dparams, src_rad, det_rad,
                              angle_grid, det_grid, angle_offset)
    spiral_pitch_factor = 2 / (2 * np.pi * 20)
    geom_hcf = HelicalConeFlatGeometry(angle_intvl, dparams, src_rad,
                                       det_rad, spiral_pitch_factor,
                                       angle_grid, det_grid, angle_offset)

    # DiscreteLp
    ind = 1
    proj_rect = dparams.insert(angle_intvl, ind)
    proj_space = FunctionSpace(proj_rect)
    # TODO: question: intervals have default index, grids not
    proj_grid = det_grid.insert(angle_grid, ind)
    npixels = proj_grid.shape
    discr_proj_space = uniform_discr(proj_space, npixels, dtype='float32')

    # np.set_printoptions(precision=4, suppress=True)
    print('\n\n angle interval:', angle_intvl, '\n det params:', dparams,
          '\n proj rectangle:', proj_rect)
    print(' vol data:', discr_data.shape,
          np.min(discr_data), np.max(discr_data), np.mean(discr_data),
          discr_vol_space.interp)
    print(' proj:', npixels)

    save_dir = '/home/jmoosmann/Documents/astra_odl/forward/'

    # PARALLEL 3D
    proj_data = astra_gpu_forward_projector_call(discr_data, geom_p3d,
                                                 discr_proj_space)
    print('\n proj p3d:', proj_data.shape, np.min(proj_data), np.max(
        proj_data), np.mean(proj_data), discr_proj_space.interp)

    # proj_data = astra_gpu_projector_call(discr_data, geom_p3d,
    #                                      discr_proj_space, 'backward')

    # proj_data.show('imshow', saveto=save_dir+'parallel3d_cuda.png')

    # CIRCULAR CONE FLAT
    proj_data = astra_gpu_forward_projector_call(discr_data, geom_ccf,
                                                 discr_proj_space)
    print('\n proj ccf:', proj_data.shape, np.min(proj_data), np.max(
        proj_data), np.mean(proj_data), discr_proj_space.interp)
    # proj_data.show('imshow', saveto=save_dir+'fanflat_cuda.png')

    # HELICAL CONE BEAM
    proj_data = astra_gpu_forward_projector_call(discr_data, geom_hcf,
                                                 discr_proj_space)
    print('\n proj hcf:', proj_data.shape, np.min(proj_data), np.max(
    proj_data), np.mean(proj_data), discr_proj_space.interp)
