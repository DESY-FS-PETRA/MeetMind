from __future__ import annotations

import csv
import json
import re
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_JSON = ROOT / "app" / "vocabulary" / "data" / "scientific_vocabulary_1000.json"
OUTPUT_CSV = ROOT / "data" / "vocabulary" / "scientific_vocabulary_1000.csv"

CATEGORY_PROFILES = OrderedDict({
    "synchrotron_beamline": {
        "label": "Synchrotron, accelerator and beamline",
        "description": "Synchrotron radiation, storage rings, insertion devices, beamline operation and beam diagnostics.",
        "keywords": [
            "synchrotron", "beamline", "beamtime", "storage ring", "undulator", "monochromator",
            "photon flux", "brilliance", "beam current", "insertion device", "PETRA", "XFEL",
        ],
    },
    "xray_optics_microscopy": {
        "label": "X-ray optics and microscopy",
        "description": "Refractive, reflective and diffractive X-ray optics, focusing and scanning microscopy.",
        "keywords": [
            "x-ray optics", "microscopy", "lens", "zone plate", "KB mirror", "nano-focus",
            "wavefront", "focal spot", "scanning microscopy", "refractive optics",
        ],
    },
    "holography_phase_coherence": {
        "label": "Holography, phase contrast and coherence",
        "description": "Near- and far-field holography, propagation, phase retrieval and coherent imaging.",
        "keywords": [
            "holography", "near-field", "far-field", "phase retrieval", "phase recovery",
            "Fresnel", "Fraunhofer", "coherence", "wavefield", "phase contrast",
        ],
    },
    "ptychography_cdi": {
        "label": "Ptychography and coherent diffraction imaging",
        "description": "Ptychographic acquisition, reconstruction engines, CDI and multi-slice methods.",
        "keywords": [
            "ptychography", "ptychographic", "CDI", "coherent diffraction", "ePIE", "difference map",
            "probe retrieval", "object retrieval", "multi-slice", "scan positions",
        ],
    },
    "tomography_inverse": {
        "label": "Tomography and inverse problems",
        "description": "CT geometries, reconstruction algorithms, regularization and inverse-problem methods.",
        "keywords": [
            "tomography", "computed tomography", "sinogram", "Radon", "reconstruction", "inverse problem",
            "ASTRA", "TomoPy", "filtered back projection", "SIRT", "CGLS", "regularization",
        ],
    },
    "spectroscopy_scanning_materials": {
        "label": "Scanning modalities, spectroscopy and materials",
        "description": "XRF, XBIC, XEOL, diffraction microscopy, spectroscopy and materials characterization.",
        "keywords": [
            "XRF", "XBIC", "XEOL", "XRD", "diffraction", "spectroscopy", "Compton",
            "photovoltaics", "thin film", "fluorescence", "absorption edge",
        ],
    },
    "detectors_acquisition": {
        "label": "Detectors, acquisition and calibration",
        "description": "Area detectors, scintillators, acquisition settings, calibration and corrections.",
        "keywords": [
            "detector", "scintillator", "Eiger", "Lambda", "sCMOS", "flat-field", "dark-field",
            "exposure time", "pixel size", "dynamic range", "calibration",
        ],
    },
    "ai_ml_image_processing": {
        "label": "AI, machine learning and image processing",
        "description": "Machine learning, deep learning, computer vision and scientific image analysis.",
        "keywords": [
            "AI", "machine learning", "deep learning", "neural network", "U-Net", "autoencoder",
            "segmentation", "classification", "denoising", "PyTorch", "TensorFlow",
        ],
    },
    "software_hpc": {
        "label": "Scientific software, programming and HPC",
        "description": "Scientific Python, C++, CUDA, clusters, reconstruction software and visualization tools.",
        "keywords": [
            "Python", "C++", "CUDA", "OpenMP", "Maxwell", "MATLAB", "PtyPy", "PyNX",
            "pyFAI", "Git", "HDF5", "HPC", "GPU",
        ],
    },
    "simulation_optimization": {
        "label": "Simulation, numerical methods and optimization",
        "description": "Wave propagation, Monte Carlo, numerical solvers, optimization and uncertainty.",
        "keywords": [
            "simulation", "Monte Carlo", "numerical", "optimization", "gradient descent", "finite difference",
            "forward model", "inverse model", "regularization", "uncertainty",
        ],
    },
    "experimental_materials": {
        "label": "Experimental methods and materials science",
        "description": "Sample environments, deposition, microscopy, photovoltaics and materials experiments.",
        "keywords": [
            "sample", "thin-film deposition", "sputtering", "SEM", "TEM", "AFM", "in situ",
            "operando", "photovoltaic", "nanostructure", "sample preparation",
        ],
    },
    "writing_projects": {
        "label": "Scientific writing, proposals and EU projects",
        "description": "Scientific papers, proposals, work packages, deliverables and project strategy.",
        "keywords": [
            "proposal", "scientific writing", "paper", "manuscript", "EU project", "Horizon Europe",
            "work package", "deliverable", "milestone", "grant", "reviewer",
        ],
    },
})

CORE_TERMS = {
    "synchrotron radiation", "storage ring", "beamline", "beamtime", "undulator", "monochromator",
    "photon flux", "PETRA III", "PETRA IV", "European XFEL", "X-ray energy", "X-ray optics",
    "compound refractive lens", "Fresnel zone plate", "Kirkpatrick–Baez mirror", "KB mirror",
    "nano-focusing", "wavefront", "X-ray microscopy", "scanning X-ray microscopy",
    "X-ray holography", "near-field holography", "far-field holography", "phase contrast imaging",
    "phase retrieval", "phase recovery", "Fresnel propagation", "coherence", "ptychography",
    "X-ray ptychography", "near-field ptychography", "multi-slice ptychography",
    "coherent diffraction imaging", "CDI", "ePIE", "difference map", "computed tomography",
    "X-ray tomography", "sinogram", "filtered back projection", "iterative reconstruction",
    "tomographic reconstruction", "ASTRA Toolbox", "TomoPy", "PtyPy", "PyNX", "pyFAI", "cSAXS code",
    "X-ray fluorescence", "XRF", "XBIC", "XEOL", "X-ray diffraction", "XRD", "nano-XRD",
    "image reconstruction", "image processing", "machine learning", "deep learning", "U-Net",
    "autoencoder", "image segmentation", "image denoising", "Python", "MATLAB", "PyTorch", "Ollama",
    "CUDA", "Maxwell cluster", "HDF5", "LaTeX", "inverse problems", "optimization",
}

EXPLICIT_ALIASES = {
    "ASTRA Toolbox": ["Astra toolbox", "ASTA toolbox", "ASTA football", "Astra football", "extra toolbox"],
    "TomoPy": ["tomo pie", "tomo pi", "tomopy"],
    "PtyPy": ["tie pie", "pty pie", "ptypy"],
    "PyNX": ["pie N X", "py N X", "pynx"],
    "pyFAI": ["pie F A I", "py F A I", "py fai"],
    "cSAXS code": ["C S A X S code", "c sax code", "sea sax code", "CSX", "CSX code", "CSAXS code", "C SAXS code", "CSX's code"],
    "MATLAB": ["mat lab", "matlib", "mat lab software"],
    "LaTeX": ["latex", "lay tech", "late tech"],
    "PtychoShelves": ["ptycho shelves", "tie-co shelves"],
    "ImageJ": ["image J", "image jay"],
    "Fiji": ["fee gee", "Fiji ImageJ"],
    "Igor Pro": ["Egor Pro", "Igor professional"],
    "OsiriX": ["Osiris", "oh siri X"],
    "PETRA III": ["PETRA 3", "Petra three", "petra tree"],
    "PETRA IV": ["PETRA 4", "Petra four", "TRA 4", "TRA-4"],
    "European XFEL": ["European X F E L", "European exfel"],
    "DESY": ["D E S Y", "desi"],
    "Maxwell cluster": ["Maxwell", "Maxwell compute cluster"],
    "Kirkpatrick–Baez mirror": ["Kirkpatrick Baez mirror", "KB mirrors", "K B mirror"],
    "compound refractive lens": ["compound refractive lenses", "C R L", "CRL"],
    "sinogram": ["synogram"],
    "sCMOS detector": ["SCMOS detector", "S C M O S detector"],
    "object retrieval": ["object retrieve"],
    "dark-field correction": ["dark-field correct", "dark field correct"],
    "machine learning": ["l learning"],
    "autoencoder": ["auto encoder", "auto encoders", "autoencoders"],
    "Ollama": ["llama"],
    "Fresnel zone plate": ["Fresnel zone plates", "zone plate"],
    "near-field holography": ["near field holography", "nearfield holography"],
    "far-field holography": ["far field holography", "farfield holography"],
    "near-field ptychography": ["near field ptychography", "nearfield ptychography"],
    "far-field ptychography": ["far field ptychography", "farfield ptychography"],
    "multi-slice ptychography": ["multislice ptychography", "multi slicing ptychography"],
    "coherent diffraction imaging": ["coherent diffractive imaging"],
    "ePIE": ["EPIE", "e pie", "extended pie"],
    "rPIE": ["RPIE", "r pie"],
    "mPIE": ["MPIE", "m pie"],
    "difference map": ["difference-map algorithm"],
    "transport of intensity equation": ["TIE equation", "transport intensity equation"],
    "Paganin phase retrieval": ["Paganin method", "Paganini method"],
    "filtered back projection": ["filtered backprojection", "F B P"],
    "simultaneous iterative reconstruction technique": ["SIRT", "simultaneous iterative reconstruction"],
    "simultaneous algebraic reconstruction technique": ["SART", "simultaneous algebraic reconstruction"],
    "algebraic reconstruction technique": ["ART", "algebraic reconstruction"],
    "conjugate gradient least squares": ["CGLS", "conjugate-gradient least squares"],
    "X-ray fluorescence": ["x ray fluorescence"],
    "X-ray beam induced current": ["x ray beam induced current", "X B I C"],
    "X-ray excited optical luminescence": ["x ray excited optical luminescence", "X E O L"],
    "X-ray diffraction": ["x ray diffraction", "X R D"],
    "scanning transmission X-ray microscopy": ["S T X M", "STXM"],
    "transmission X-ray microscopy": ["T X M", "TXM"],
    "small-angle X-ray scattering": ["S A X S", "SAXS"],
    "wide-angle X-ray scattering": ["W A X S", "WAXS"],
    "grazing-incidence small-angle X-ray scattering": ["GI SAXS", "GISAXS"],
    "grazing-incidence wide-angle X-ray scattering": ["GI WAXS", "GIWAXS"],
    "U-Net": ["U net", "UNet"],
    "VGG19": ["VGG 19", "V G G nineteen"],
    "scikit-learn": ["sci kit learn", "scikit learn"],
    "PyTorch": ["pie torch", "py torch"],
    "TensorFlow": ["tensor flow"],
    "OpenCV": ["open C V"],
    "OpenMP": ["open M P"],
    "HDF5": ["H D F five", "HDF five"],
    "NeXus format": ["Nexus format", "N X us format"],
    "Jupyter Notebook": ["Jupiter notebook"],
}


def lines(block: str) -> list[str]:
    return [line.strip() for line in block.strip().splitlines() if line.strip()]


SEEDS = {
    "synchrotron_beamline": lines(r"""
synchrotron radiation
storage ring
electron storage ring
linear accelerator
LINAC
booster synchrotron
electron beam
photon beam
insertion device
undulator
planar undulator
helical undulator
in-vacuum undulator
cryogenic permanent magnet undulator
wiggler
bending magnet
beamline
beamtime
beam current
stored current
bunch pattern
bunch train
bunch length
bunch spacing
top-up injection
photon flux
spectral flux
brilliance
brightness
emittance
horizontal emittance
vertical emittance
energy spread
beam divergence
beam size
source size
source point
machine optics
beta function
orbit correction
fast orbit feedback
slow orbit feedback
beam position monitor
BPM
current transformer
beam loss monitor
machine protection system
front end
primary slit
secondary slit
beam-defining aperture
beam stop
photon shutter
fast shutter
safety shutter
white beam
pink beam
monochromatic beam
harmonic rejection
higher harmonic
monochromator
double-crystal monochromator
channel-cut monochromator
silicon monochromator
Si(111) monochromator
Si(311) monochromator
energy calibration
absorption edge
energy scan
rocking curve
Bragg angle
Bragg reflection
Darwin width
beam stability
thermal drift
heat load
cryogenic cooling
water cooling
vacuum chamber
ultra-high vacuum
beam transport
beam delivery
experimental hutch
optics hutch
control hutch
beamline control system
EPICS
TANGO controls
PETRA III
PETRA IV
European XFEL
FLASH
DESY
P05 beamline
P06 beamline
P21.2 beamline
"""),
    "xray_optics_microscopy": lines(r"""
X-ray optics
refractive X-ray optics
reflective X-ray optics
diffractive X-ray optics
compound refractive lens
CRL
beryllium lens
aluminium lens
polymer X-ray lens
kinoform lens
Fresnel zone plate
zone plate
binary zone plate
multilevel zone plate
multilayer Laue lens
MLL
Kirkpatrick–Baez mirror
KB mirror
elliptical mirror
parabolic mirror
toroidal mirror
bimorph mirror
multilayer mirror
supermirror
grazing-incidence mirror
X-ray waveguide
capillary optic
polycapillary optic
X-ray prism
beam expander
beam condenser
condenser optic
order-sorting aperture
central stop
pinhole
aperture
slit system
secondary source
nano-focusing
micro-focusing
nanobeam
microbeam
focal spot
spot size
full width at half maximum
FWHM
depth of focus
working distance
focal length
numerical aperture
acceptance angle
collection angle
magnification
geometric magnification
optical transfer function
modulation transfer function
point spread function
line spread function
wavefront
wavefront error
wavefront sensing
wavefield characterization
beam caustic
beam waist
Rayleigh length
aberration
spherical aberration
chromatic aberration
astigmatism
coma
mirror slope error
surface roughness
figure error
alignment tolerance
optical alignment
X-ray microscopy
scanning X-ray microscopy
transmission X-ray microscopy
full-field X-ray microscopy
scanning transmission X-ray microscopy
STXM
TXM
hard X-ray microscopy
soft X-ray microscopy
nano-X-ray microscopy
micro-X-ray microscopy
scanning Compton X-ray microscopy
X-ray nanoscopy
X-ray magnification microscopy
projection microscopy
contact microscopy
dark-field X-ray microscopy
Bragg coherent diffraction imaging
zoom tomography
optical lens
visible-light microscope
objective lens
scintillator-coupled microscope
"""),
    "holography_phase_coherence": lines(r"""
X-ray holography
near-field holography
far-field holography
inline holography
off-axis holography
Fourier-transform holography
Fourier holography
reference-beam holography
lensless holography
digital holography
holographic imaging
holographic reconstruction
hologram
reference wave
object wave
interference pattern
fringe pattern
fringe visibility
fringe contrast
phase contrast imaging
propagation-based phase contrast
inline phase contrast
analyzer-based imaging
grating interferometry
Talbot interferometry
Talbot–Lau interferometry
speckle-based imaging
edge illumination
phase retrieval
phase recovery
phase unwrapping
phase wrapping
phase map
projected phase
complex transmission function
complex refractive index
refractive index decrement
absorption index
optical path length
projected electron density
Fresnel diffraction
Fraunhofer diffraction
Fresnel propagation
Fraunhofer propagation
angular spectrum method
Fresnel transform
Fourier transform propagation
Rayleigh–Sommerfeld propagation
Kirchhoff diffraction integral
Huygens–Fresnel principle
paraxial approximation
near-field regime
far-field regime
Fresnel number
Fraunhofer distance
propagation distance
defocus distance
focus-to-detector distance
sample-to-detector distance
coherence
spatial coherence
temporal coherence
partial coherence
transverse coherence
longitudinal coherence
coherence length
coherence area
mutual coherence function
complex degree of coherence
coherent mode decomposition
mixed-state model
source coherence
visibility reduction
transport of intensity equation
TIE
Paganin phase retrieval
Paganin method
contrast transfer function
CTF
contrast transfer function inversion
multi-distance phase retrieval
single-distance phase retrieval
holotomography
phase tomography
phase-contrast tomography
wave propagation
wavefield propagation
wavefield retrieval
phase diversity
Gerchberg–Saxton algorithm
hybrid input-output algorithm
error-reduction algorithm
support constraint
positivity constraint
phase constraint
amplitude constraint
Fourier-domain constraint
real-space constraint
"""),
    "ptychography_cdi": lines(r"""
ptychography
X-ray ptychography
near-field ptychography
far-field ptychography
Fourier ptychography
scanning ptychography
Bragg ptychography
reflection ptychography
soft X-ray ptychography
hard X-ray ptychography
multi-slice ptychography
multislice ptychography
3D ptychography
ptychographic tomography
ptychographic X-ray computed tomography
PXCT
spectro-ptychography
fluorescence ptychography
magnetic ptychography
time-resolved ptychography
continuous-scan ptychography
fly-scan ptychography
position-resolved coherent diffraction
coherent diffraction imaging
CDI
Bragg coherent diffraction imaging
BCDI
single-particle imaging
phase-retrieval transfer function
ptychographic reconstruction
probe retrieval
object retrieval
probe function
object function
illumination function
exit wave
diffraction pattern
far-field diffraction pattern
near-field diffraction pattern
scan grid
scan positions
raster scan
spiral scan
Fermat spiral
random scan
scan overlap
overlap constraint
redundancy
ptychographic redundancy
position refinement
position correction
probe-position correction
scan-position error
sample drift
probe drift
partial coherence model
mixed-state ptychography
multiple probe modes
orthogonal probe relaxation
OPR
multi-mode reconstruction
multi-wavelength ptychography
multi-energy ptychography
multi-slice propagation
slice thickness
inter-slice propagation
projection approximation
weak-phase approximation
strong-phase object
extended ptychographic iterative engine
ePIE
regularized PIE
rPIE
momentum-accelerated PIE
mPIE
difference map
DM algorithm
maximum-likelihood ptychography
ML ptychography
conjugate-gradient ptychography
least-squares ptychography
alternating projections
projection algorithms
RAAR algorithm
relaxed averaged alternating reflections
Wigner distribution deconvolution
WDD
ptychographic iterative engine
PIE
probe normalization
object normalization
probe constraint
object constraint
support update
shrink-wrap algorithm
phase ramp correction
linear phase ramp
Fourier shift theorem
subpixel registration
ptychographic resolution
Fourier ring correlation
FRC
phase retrieval consistency
reconstruction error
Fourier error
real-space error
likelihood metric
PtyPy
PyNX
PtychoShelves
cSAXS ptychography code
"""),
    "tomography_inverse": lines(r"""
computed tomography
CT
X-ray tomography
micro-computed tomography
micro-CT
nano-computed tomography
nano-CT
synchrotron tomography
absorption tomography
phase-contrast tomography
holotomography
ptychographic tomography
laminography
X-ray laminography
computed laminography
cone-beam tomography
parallel-beam tomography
fan-beam tomography
helical tomography
spiral tomography
limited-angle tomography
sparse-view tomography
interior tomography
dynamic tomography
time-resolved tomography
spectral tomography
multi-energy tomography
dual-energy tomography
hyperspectral tomography
fluorescence tomography
diffraction tomography
X-ray diffraction tomography
projection data
radiograph
projection image
sinogram
sinogram preprocessing
sinogram alignment
sinogram filtering
Radon transform
inverse Radon transform
Fourier slice theorem
central slice theorem
projection theorem
back projection
filtered back projection
FBP
Feldkamp–Davis–Kress algorithm
FDK
algebraic reconstruction technique
ART
simultaneous algebraic reconstruction technique
SART
simultaneous iterative reconstruction technique
SIRT
conjugate gradient least squares
CGLS
expectation maximization
maximum-likelihood expectation maximization
MLEM
ordered subsets expectation maximization
OSEM
iterative reconstruction
model-based iterative reconstruction
statistical reconstruction
total variation reconstruction
total variation regularization
TV regularization
Tikhonov regularization
L1 regularization
L2 regularization
sparsity regularization
compressed sensing
plug-and-play reconstruction
learned iterative reconstruction
neural reconstruction
physics-informed reconstruction
joint reconstruction
multi-modal reconstruction
center of rotation
rotation-axis alignment
axis tilt
projection alignment
vertical alignment
horizontal alignment
cor alignment
ring artifact
stripe artifact
beam hardening
metal artifact
motion artifact
missing wedge
missing cone
truncation artifact
limited-angle artifact
flat-field correction
dark-field correction
phase retrieval before tomography
phase retrieval after tomography
volume reconstruction
voxel grid
isotropic voxel
anisotropic voxel
volume rendering
orthogonal slice
maximum intensity projection
minimum intensity projection
ASTRA Toolbox
TomoPy
cSAXS tomography code
"""),
    "spectroscopy_scanning_materials": lines(r"""
X-ray fluorescence
XRF
micro-XRF
nano-XRF
scanning X-ray fluorescence
X-ray fluorescence microscopy
X-ray fluorescence tomography
XRF tomography
fluorescence yield
fluorescence detector
silicon drift detector
SDD
energy-dispersive detector
energy-dispersive spectroscopy
EDS
wavelength-dispersive spectroscopy
WDS
X-ray absorption spectroscopy
XAS
X-ray absorption near-edge structure
XANES
extended X-ray absorption fine structure
EXAFS
absorption edge
K edge
L edge
M edge
edge jump
white line
pre-edge feature
post-edge region
X-ray emission spectroscopy
XES
resonant inelastic X-ray scattering
RIXS
X-ray photoelectron spectroscopy
XPS
X-ray beam induced current
XBIC
X-ray excited optical luminescence
XEOL
optical luminescence
photoluminescence
cathodoluminescence
X-ray diffraction
XRD
powder diffraction
single-crystal diffraction
wide-angle X-ray scattering
WAXS
small-angle X-ray scattering
SAXS
ultra-small-angle X-ray scattering
USAXS
grazing-incidence X-ray diffraction
GIXRD
grazing-incidence small-angle X-ray scattering
GISAXS
grazing-incidence wide-angle X-ray scattering
GIWAXS
azimuthal integration
radial integration
cake integration
2D integration
1D integration
Debye–Scherrer ring
Bragg peak
Bragg diffraction
reciprocal space
reciprocal-space map
RSM
scattering vector
momentum transfer
q vector
2-theta
Miller indices
lattice parameter
crystal orientation
texture analysis
strain mapping
residual strain
phase identification
Rietveld refinement
pair distribution function
PDF analysis
nano-XRD
scanning X-ray diffraction microscopy
SXDM
diffraction contrast
Bragg microscopy
scanning Compton X-ray microscopy
Compton scattering
Compton profile
photovoltaics
solar cell
thin-film solar cell
perovskite solar cell
CIGS solar cell
organic photovoltaic
charge-carrier collection
carrier lifetime
"""),
    "detectors_acquisition": lines(r"""
X-ray detector
area detector
pixel detector
photon-counting detector
integrating detector
hybrid pixel detector
single-photon counting
direct detector
indirect detector
scintillator
scintillator screen
Gadox scintillator
LuAG scintillator
YAG scintillator
CdTe detector
silicon detector
sCMOS detector
CMOS detector
CCD detector
Eiger detector
Pilatus detector
Lambda detector
Medipix detector
Timepix detector
Jungfrau detector
Gotthard detector
AGIPD detector
DSSC detector
LPD detector
flat-panel detector
photodiode
avalanche photodiode
APD
photomultiplier tube
PMT
silicon drift detector
energy resolution
spatial resolution
temporal resolution
pixel size
effective pixel size
field of view
dynamic range
bit depth
full well capacity
readout noise
dark current
shot noise
Poisson noise
gain
conversion gain
detector gain
count rate
dead time
pile-up
charge sharing
point spread function
detector point spread function
modulation transfer function
detective quantum efficiency
DQE
quantum efficiency
exposure time
integration time
frame rate
readout rate
trigger mode
external trigger
internal trigger
continuous acquisition
burst mode
region of interest
ROI
binning
hardware binning
software binning
flat-field image
dark-field image
flat-field correction
dark-current correction
bad pixel map
dead pixel
hot pixel
pixel mask
threshold scan
energy threshold
energy calibration
detector calibration
geometric calibration
distortion correction
lens distortion
background subtraction
normalization
image registration
metadata
HDF5
NeXus format
TIFF
EDF file
CBF file
"""),
    "ai_ml_image_processing": lines(r"""
artificial intelligence
AI
machine learning
deep learning
neural network
artificial neural network
convolutional neural network
CNN
recurrent neural network
RNN
long short-term memory
LSTM
transformer
vision transformer
ViT
graph neural network
GNN
multilayer perceptron
MLP
autoencoder
convolutional autoencoder
variational autoencoder
VAE
denoising autoencoder
sparse autoencoder
generative adversarial network
GAN
conditional GAN
CycleGAN
Wasserstein GAN
U-Net
3D U-Net
residual U-Net
attention U-Net
ResNet
VGG19
DenseNet
EfficientNet
Mask R-CNN
YOLO
support vector machine
SVM
naive Bayes
random forest
gradient boosting
XGBoost
k-nearest neighbors
KNN
principal component analysis
PCA
independent component analysis
ICA
nonnegative matrix factorization
NMF
clustering
k-means clustering
DBSCAN
hierarchical clustering
object detection
image classification
image segmentation
semantic segmentation
instance segmentation
binary segmentation
multi-class segmentation
feature extraction
feature engineering
image denoising
noise reduction
image deblurring
super-resolution
image restoration
artifact removal
background removal
anomaly detection
outlier detection
data augmentation
transfer learning
fine-tuning
self-supervised learning
semi-supervised learning
unsupervised learning
supervised learning
reinforcement learning
physics-informed neural network
PINN
physics-guided machine learning
scientific machine learning
operator learning
neural operator
Fourier neural operator
FNO
deep image prior
Noise2Noise
Noise2Void
Noise2Inverse
contrastive learning
metric learning
embedding model
feature embedding
latent space
latent representation
training dataset
validation dataset
test dataset
cross-validation
hyperparameter optimization
learning rate
batch size
loss function
L1 loss
L2 loss
mean squared error
structural similarity index
SSIM
peak signal-to-noise ratio
PSNR
intersection over union
IoU
precision
recall
F1 score
confusion matrix
overfitting
underfitting
regularization
dropout
batch normalization
layer normalization
model inference
model deployment
MLOps
"""),
    "software_hpc": lines(r"""
Python
C
C++
Fortran
MATLAB
Spyder
Jupyter Notebook
JupyterLab
NumPy
SciPy
Matplotlib
Pandas
scikit-image
scikit-learn
TensorFlow
Keras
PyTorch
torchvision
OpenCV
OpenMP
MPI
CUDA
cuDNN
CMake
Git
GitHub
GitLab
Docker
Singularity
Apptainer
Conda
Mamba
virtual environment
pip
Linux
PowerShell
Bash
SLURM
batch job
job scheduler
compute node
GPU node
CPU node
high-performance computing
HPC
parallel computing
parallelization
multi-threading
multi-processing
distributed computing
data parallelism
model parallelism
mixed-precision training
automatic mixed precision
AMP
CUDA kernel
GPU memory
out-of-memory error
memory profiling
performance profiling
Maxwell cluster
SSH
remote login
file system
Lustre file system
GPFS
HDF5
h5py
Zarr
NumPy array
memory mapping
Dask
Ray
FastAPI
WebSocket
REST API
SQLAlchemy
SQLite
PostgreSQL
FAISS
ChromaDB
Ollama
Whisper
faster-whisper
ASTRA Toolbox
TomoPy
PtyPy
PyNX
pyFAI
cSAXS code
PetraPy
Avizo
Fiji
ImageJ
Igor Pro
OsiriX
ParaView
VTK
3D Slicer
Blender
Adobe Illustrator
Adobe Lightroom
OpenPyXL
LaTeX
Overleaf
BibTeX
"""),
    "simulation_optimization": lines(r"""
simulation
beamline simulation
X-ray optics simulation
wave propagation simulation
Monte Carlo simulation
Monte Carlo ray tracing
X-ray matter interaction
photon transport
electron transport
particle transport
Geant4
FLUKA
PENELOPE
McXtrace
SHADOW
ShadowOui
OASYS
SRW
Synchrotron Radiation Workshop
wavefront propagation simulation
Fresnel propagation simulation
finite-difference method
finite-element method
boundary-element method
spectral method
pseudo-spectral method
finite-volume method
fast Fourier transform
FFT
inverse fast Fourier transform
IFFT
convolution
cross-correlation
autocorrelation
interpolation
nearest-neighbor interpolation
bilinear interpolation
bicubic interpolation
spline interpolation
resampling
oversampling
zero padding
Fourier padding
numerical integration
numerical differentiation
ordinary differential equation
ODE
partial differential equation
PDE
linear solver
nonlinear solver
iterative solver
direct solver
conjugate gradient
preconditioned conjugate gradient
GMRES
LSQR
gradient descent
stochastic gradient descent
Adam optimizer
L-BFGS
Newton method
Gauss–Newton method
Levenberg–Marquardt algorithm
alternating direction method of multipliers
ADMM
proximal gradient
FISTA
ISTA
coordinate descent
convex optimization
nonconvex optimization
constrained optimization
unconstrained optimization
multi-objective optimization
Bayesian optimization
global optimization
local optimization
objective function
cost function
forward model
inverse model
adjoint model
Jacobian
Hessian
regularization parameter
hyperparameter
Lagrange multiplier
uncertainty quantification
error propagation
sensitivity analysis
parameter estimation
model calibration
simulation validation
synthetic data
digital phantom
Shepp–Logan phantom
multislice simulation
projection approximation
beam propagation method
BPM simulation
"""),
    "experimental_materials": lines(r"""
experimental setup
sample environment
sample holder
sample mount
sample stage
rotation stage
translation stage
piezo stage
nanopositioning
interferometry
laser interferometer
capacitive sensor
encoder
closed-loop control
open-loop control
position feedback
vibration isolation
active vibration control
thermal stabilization
temperature controller
cryostat
heating stage
cooling stage
vacuum furnace
pressure cell
flow cell
reaction cell
in situ measurement
operando measurement
ex situ measurement
time-resolved measurement
pump-probe experiment
sample preparation
focused ion beam
FIB
scanning electron microscopy
SEM
transmission electron microscopy
TEM
scanning transmission electron microscopy
STEM
atomic force microscopy
AFM
optical microscopy
confocal microscopy
thin-film deposition
physical vapor deposition
PVD
chemical vapor deposition
CVD
atomic layer deposition
ALD
sputter deposition
magnetron sputtering
thermal evaporation
electron-beam evaporation
spin coating
dip coating
blade coating
spray coating
annealing
rapid thermal annealing
calcination
crystallization
nucleation
grain boundary
grain size
crystallite size
thin film
multilayer film
heterostructure
nanostructure
nanoparticle
nanowire
quantum dot
porous material
polycrystalline material
single crystal
amorphous material
semiconductor
photovoltaic material
perovskite material
CIGS
silicon solar cell
organic semiconductor
charge carrier
carrier diffusion
carrier recombination
carrier mobility
defect density
interface layer
buffer layer
absorber layer
electrode
contact layer
sample damage
radiation damage
dose
dose rate
critical dose
beam-induced damage
"""),
    "writing_projects": lines(r"""
scientific writing
technical writing
academic writing
manuscript
research paper
journal article
conference paper
conference abstract
extended abstract
scientific report
technical report
progress report
annual report
executive summary
abstract
introduction
methods section
results section
discussion section
conclusion
supplementary information
figure caption
table caption
cover letter
response to reviewers
reviewer comment
peer review
revision letter
proofreading
copy editing
citation
reference management
bibliography
BibTeX
LaTeX
Overleaf
scientific presentation
conference presentation
poster presentation
strategic proposal writing
research proposal
project proposal
grant proposal
funding application
call text
call topic
scope
scientific excellence
state of the art
research gap
project objective
specific objective
expected outcome
expected impact
methodology
implementation plan
work plan
work package
task
deliverable
milestone
critical path
Gantt chart
risk assessment
risk mitigation
contingency plan
resource allocation
person month
budget
cost category
equipment cost
travel cost
personnel cost
consortium
consortium agreement
collaboration agreement
memorandum of understanding
project coordinator
principal investigator
beneficiary
associated partner
stakeholder
advisory board
steering committee
project management
quality assurance
data management plan
DMP
open science
FAIR data
research data management
dissemination
communication
exploitation
intellectual property
IPR
technology readiness level
TRL
EU project
Horizon Europe
European Research Council
ERC
Marie Skłodowska-Curie Actions
MSCA
European Innovation Council
EIC
proposal evaluation
evaluation criterion
excellence criterion
impact criterion
implementation criterion
ethics self-assessment
gender dimension
open access
project amendment
periodic report
final report
"""),
}

# Controlled expansions add valid specialist phrases while keeping the source
# lists readable. Only combinations commonly used in the corresponding field
# are generated.
EXPANSIONS = {
    "synchrotron_beamline": [
        (["horizontal", "vertical"], ["beam size", "beam divergence", "emittance", "orbit", "focusing"]),
        (["fast", "slow"], ["beam feedback", "orbit feedback", "data acquisition"]),
        (["photon", "electron"], ["beam diagnostics", "beam energy", "beam transport"]),
    ],
    "xray_optics_microscopy": [
        (["hard X-ray", "soft X-ray", "tender X-ray"], ["optics", "microscopy", "focusing", "imaging"]),
        (["nano", "micro"], ["focusing optic", "probe", "beam", "spot"]),
        (["horizontal", "vertical"], ["focusing mirror", "beam profile", "focal size"]),
    ],
    "holography_phase_coherence": [
        (["single-distance", "multi-distance", "iterative", "regularized"], ["phase retrieval", "phase reconstruction"]),
        (["near-field", "far-field", "Fourier-domain", "real-space"], ["propagation", "reconstruction", "constraint"]),
        (["spatial", "temporal", "transverse", "longitudinal"], ["coherence measurement", "coherence function"]),
    ],
    "ptychography_cdi": [
        (["single-mode", "multi-mode", "mixed-state", "multi-slice"], ["ptychographic reconstruction", "probe retrieval"]),
        (["position", "probe", "object", "phase-ramp"], ["correction", "refinement", "constraint"]),
        (["maximum-likelihood", "least-squares", "gradient-based"], ["ptychographic optimization", "ptychographic solver"]),
    ],
    "tomography_inverse": [
        (["parallel-beam", "cone-beam", "limited-angle", "sparse-view"], ["reconstruction", "geometry", "artifact correction"]),
        (["L1", "L2", "total variation", "sparsity"], ["regularization", "penalty", "prior"]),
        (["projection", "sinogram", "volume"], ["alignment", "normalization", "filtering"]),
    ],
    "spectroscopy_scanning_materials": [
        (["micro", "nano", "scanning"], ["XRF", "XRD", "spectroscopy", "diffraction mapping"]),
        (["elemental", "chemical", "strain", "orientation"], ["mapping", "contrast", "analysis"]),
        (["K-edge", "L-edge", "M-edge"], ["spectroscopy", "mapping", "analysis"]),
    ],
    "detectors_acquisition": [
        (["high-speed", "high-dynamic-range", "low-noise"], ["detector", "readout", "acquisition"]),
        (["pixel", "energy", "gain", "geometric"], ["calibration", "correction", "map"]),
        (["online", "real-time", "streaming"], ["data acquisition", "image correction", "detector monitoring"]),
    ],
    "ai_ml_image_processing": [
        (["supervised", "self-supervised", "unsupervised", "physics-informed"], ["image denoising", "image reconstruction", "representation learning"]),
        (["2D", "3D", "multi-scale"], ["U-Net", "convolutional network", "image segmentation"]),
        (["training", "validation", "inference"], ["pipeline", "workflow", "performance"]),
    ],
    "software_hpc": [
        (["CPU", "GPU", "multi-GPU", "distributed"], ["parallelization", "training", "inference", "computing"]),
        (["Python", "C++", "CUDA"], ["implementation", "pipeline", "optimization"]),
        (["containerized", "reproducible", "automated"], ["workflow", "deployment", "environment"]),
    ],
    "simulation_optimization": [
        (["forward", "inverse", "adjoint"], ["simulation", "solver", "model"]),
        (["deterministic", "stochastic", "Bayesian"], ["optimization", "parameter estimation", "uncertainty analysis"]),
        (["first-order", "second-order", "gradient-free"], ["optimization method", "solver"]),
    ],
    "experimental_materials": [
        (["in situ", "operando", "time-resolved"], ["X-ray imaging", "tomography", "diffraction", "spectroscopy"]),
        (["thin-film", "nanostructured", "polycrystalline"], ["sample", "material", "device"]),
        (["thermal", "mechanical", "electrical"], ["sample environment", "stability", "characterization"]),
    ],
    "writing_projects": [
        (["scientific", "technical", "strategic"], ["proposal", "report", "communication"]),
        (["project", "work-package", "task-level"], ["planning", "risk assessment", "resource allocation"]),
        (["EU", "national", "institutional"], ["funding call", "proposal evaluation", "project reporting"]),
    ],
}


def normalise(value: str) -> str:
    value = value.replace("–", "-").replace("—", "-")
    value = re.sub(r"\s+", " ", value.strip())
    return value.casefold()


def auto_aliases(term: str) -> list[str]:
    variants: list[str] = []
    if "X-ray" in term:
        variants.append(term.replace("X-ray", "X ray"))
    if "near-field" in term:
        variants.append(term.replace("near-field", "near field"))
    if "far-field" in term:
        variants.append(term.replace("far-field", "far field"))
    if "multi-slice" in term:
        variants.append(term.replace("multi-slice", "multislice"))
    if "time-resolved" in term:
        variants.append(term.replace("time-resolved", "time resolved"))
    if "high-performance" in term:
        variants.append(term.replace("high-performance", "high performance"))
    if "work-package" in term:
        variants.append(term.replace("work-package", "work package"))
    return variants


def build_terms() -> list[dict]:
    collected: OrderedDict[str, dict] = OrderedDict()

    def add(category: str, term: str) -> None:
        cleaned = re.sub(r"\s+", " ", term.strip())
        key = normalise(cleaned)
        if not cleaned or key in collected:
            return
        aliases = []
        for alias in [*EXPLICIT_ALIASES.get(cleaned, []), *auto_aliases(cleaned)]:
            if normalise(alias) != key and alias not in aliases:
                aliases.append(alias)
        priority = "core" if cleaned in CORE_TERMS else "domain"
        collected[key] = {
            "category": category,
            "canonical_term": cleaned,
            "aliases": aliases,
            "priority": priority,
        }

    for category, values in SEEDS.items():
        for term in values:
            add(category, term)
        for modifiers, nouns in EXPANSIONS.get(category, []):
            for modifier in modifiers:
                for noun in nouns:
                    add(category, f"{modifier} {noun}")

    # Additional safe variants for acronyms and expanded names.
    acronym_pairs = [
        ("coherent diffraction imaging", "CDI"),
        ("scanning transmission X-ray microscopy", "STXM"),
        ("transmission X-ray microscopy", "TXM"),
        ("X-ray fluorescence", "XRF"),
        ("X-ray beam induced current", "XBIC"),
        ("X-ray excited optical luminescence", "XEOL"),
        ("X-ray absorption spectroscopy", "XAS"),
        ("X-ray absorption near-edge structure", "XANES"),
        ("extended X-ray absorption fine structure", "EXAFS"),
        ("small-angle X-ray scattering", "SAXS"),
        ("wide-angle X-ray scattering", "WAXS"),
        ("grazing-incidence small-angle X-ray scattering", "GISAXS"),
        ("grazing-incidence wide-angle X-ray scattering", "GIWAXS"),
        ("computed tomography", "CT"),
        ("filtered back projection", "FBP"),
    ]
    for expanded, acronym in acronym_pairs:
        for item in collected.values():
            if item["canonical_term"] == expanded and acronym not in item["aliases"]:
                item["aliases"].append(acronym)

    category_quotas = OrderedDict({
        "synchrotron_beamline": 80,
        "xray_optics_microscopy": 85,
        "holography_phase_coherence": 90,
        "ptychography_cdi": 95,
        "tomography_inverse": 100,
        "spectroscopy_scanning_materials": 90,
        "detectors_acquisition": 80,
        "ai_ml_image_processing": 100,
        "software_hpc": 85,
        "simulation_optimization": 75,
        "experimental_materials": 65,
        "writing_projects": 55,
    })
    by_category: dict[str, list[dict]] = {key: [] for key in category_quotas}
    for item in collected.values():
        by_category[item["category"]].append(item)

    entries: list[dict] = []
    for category, quota in category_quotas.items():
        available = by_category.get(category, [])
        if len(available) < quota:
            raise RuntimeError(
                f"Category {category} has {len(available)} terms but needs {quota}"
            )
        # Core entries are selected before domain entries within each category.
        ranked = sorted(
            available,
            key=lambda item: (0 if item["priority"] == "core" else 1),
        )
        entries.extend(ranked[:quota])

    if len(entries) != 1000:
        raise RuntimeError(f"Expected 1000 terms, generated {len(entries)}")
    for index, item in enumerate(entries, start=1):
        item["id"] = index
    return entries


def main() -> None:
    terms = build_terms()
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": "2.0",
        "description": (
            "Adaptive scientific vocabulary for synchrotron, X-ray imaging, holography, "
            "ptychography, tomography, AI/ML, scientific computing and research projects."
        ),
        "term_count": len(terms),
        "category_count": len(CATEGORY_PROFILES),
        "categories": CATEGORY_PROFILES,
        "terms": terms,
        "notes": [
            "Only a bounded active subset is sent to Whisper at any time.",
            "Aliases are used for contextual, confidence-aware correction.",
            "The ambiguous name Nεo 2.0 is intentionally excluded until its canonical spelling is confirmed.",
        ],
    }
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "category", "canonical_term", "aliases", "priority"],
        )
        writer.writeheader()
        for item in terms:
            writer.writerow({
                "id": item["id"],
                "category": item["category"],
                "canonical_term": item["canonical_term"],
                "aliases": "; ".join(item["aliases"]),
                "priority": item["priority"],
            })

    print(f"Created {len(terms)} terms across {len(CATEGORY_PROFILES)} categories")
    print(OUTPUT_JSON)
    print(OUTPUT_CSV)


if __name__ == "__main__":
    main()
