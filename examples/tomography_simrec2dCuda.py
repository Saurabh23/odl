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

# Imports for common Python 2/3 codebase
from __future__ import print_function, division, absolute_import
from future import standard_library
standard_library.install_aliases()

from math import sin, cos, pi
from time import time
import matplotlib.pyplot as plt
import numpy as np

import odl
import SimRec2DPy as SR
import odl.operator.solvers as solvers


class ProjectionGeometry(object):
    """ Geometry for a specific projection
    """
    def __init__(self, sourcePosition, detectorOrigin, pixelDirection):
        self.sourcePosition = sourcePosition
        self.detectorOrigin = detectorOrigin
        self.pixelDirection = pixelDirection


class CudaProjector(odl.LinearOperator):
    """ A projector that creates several projections as defined by geometries
    """
    def __init__(self, volumeOrigin, voxelSize, nVoxels, nPixels, stepSize,
                 geometries, domain, range):
        self.geometries = geometries
        self.domain = domain
        self.range = range
        self.forward = SR.SRPyCuda.CudaForwardProjector(
            nVoxels, volumeOrigin, voxelSize, nPixels, stepSize)
        self._adjoint = CudaBackProjector(
            volumeOrigin, voxelSize, nVoxels, nPixels, stepSize, geometries,
            range, domain)

    def _apply(self, data, out):
        # Create projector
        self.forward.setData(data.data_ptr)

        # Project all geometries
        for i in range(len(self.geometries)):
            geo = self.geometries[i]
            self.forward.project(geo.sourcePosition, geo.detectorOrigin,
                                 geo.pixelDirection, out[i].data_ptr)

    @property
    def adjoint(self):
        return self._adjoint


class CudaBackProjector(odl.LinearOperator):
    def __init__(self, volumeOrigin, voxelSize, nVoxels, nPixels, stepSize,
                 geometries, domain, range):
        self.geometries = geometries
        self.domain = domain
        self.range = range
        self.back = SR.SRPyCuda.CudaBackProjector(nVoxels, volumeOrigin,
                                                  voxelSize, nPixels, stepSize)

    def _apply(self, projections, out):
        # Zero out the return data
        out.set_zero()

        # Append all projections
        for i in range(len(self.geometries)):
            geo = self.geometries[i]
            self.back.backProject(
                geo.sourcePosition, geo.detectorOrigin, geo.pixelDirection,
                projections[i].data_ptr, out.data_ptr)


# Set geometry parameters
volumeSize = np.array([20.0, 20.0])
volumeOrigin = -volumeSize/2.0

detectorSize = 50.0
detectorOrigin = -detectorSize/2.0

sourceAxisDistance = 20.0
detectorAxisDistance = 20.0

# Discretization parameters
nVoxels = np.array([1000, 1000])
nPixels = 1000
nProjection = 1000

# Scale factors
voxelSize = volumeSize/nVoxels
pixelSize = detectorSize/nPixels
stepSize = voxelSize.max()

# Define projection geometries
geometries = []
for theta in np.linspace(0, 2*pi, nProjection, endpoint=False):
    x0 = np.array([cos(theta), sin(theta)])
    y0 = np.array([-sin(theta), cos(theta)])

    projSourcePosition = -sourceAxisDistance * x0
    projDetectorOrigin = detectorAxisDistance * x0 + detectorOrigin * y0
    projPixelDirection = y0 * pixelSize
    geometries.append(ProjectionGeometry(
        projSourcePosition, projDetectorOrigin, projPixelDirection))

# Define the space of one projection
projectionSpace = odl.L2(odl.Interval(0, detectorSize))

# Discretize projection space
projectionDisc = odl.l2_uniform_discretization(projectionSpace, nPixels,
                                               impl='cuda')

# Create the data space, which is the Cartesian product of the
# single projection spaces
dataDisc = odl.ProductSpace(projectionDisc, nProjection)

# Define the reconstruction space
reconSpace = odl.L2(odl.Rectangle([0, 0], volumeSize))

# Discretize the reconstruction space
reconDisc = odl.l2_uniform_discretization(reconSpace, nVoxels, impl='cuda')

# Create a phantom
phantom = SR.SRPyUtils.phantom(nVoxels)
phantomVec = reconDisc.element(phantom)

# Make the operator
projector = CudaProjector(volumeOrigin, voxelSize, nVoxels, nPixels,
                          stepSize, geometries, reconDisc, dataDisc)

# Apply once to find norm estimate
projections = projector(phantomVec)
recon = projector.T(projections)
normEst = recon.norm() / phantomVec.norm()

# Define function to plot each result
tstart = time()

# plt.figure()
# plt.ion()
# plt.set_cmap('bone')


def plotResult(x):
    print('Elapsed: {}'.format(time() - tstart))
    # plt.imshow(x[:].reshape(nVoxels))
    # plt.draw()
    # print((x-phantomVec).norm())
    # plt.pause(0.01)

# Solve using landweber
x = reconDisc.zero()
solvers.landweber(projector, x, projections, 10, omega=0.4/normEst,
                  partial=solvers.ForEachPartial(plotResult))
# solvers.landweber(projector, x, projections, 10, omega=0.4/normEst,
#                   partial=solvers.PrintIterationPartial())
# solvers.conjugate_gradient(projector, x, projections, 20,
#                            partial=solvers.ForEachPartial(plotResult))

plt.imshow(x[:].reshape(nVoxels))
plt.show()
