#!/bin/bash
#PBS -S /bin/bash
#PBS -l select=4:ncpus=1:mem=4gb
#PBS -l place=scatter
#PBS -l walltime=00:01:00
#PBS -q charon_2h
#PBS -N sing_mpi_test
#PBS -j oe

set -x

which python3

# run from the repository directory
cd "/auto/liberec3-tul/home/pavel_exner/workspace/singularity_tryout_3" || exit
pwd

python3 singularity_exec_mpi.py -i flow123d-geomop-master_8d5574fc2.sif -n 4 -m /usr/local/mpich_3.4.2/bin/mpiexec python_script_runner.sh
