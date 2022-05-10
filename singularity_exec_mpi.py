import os
import sys
import shutil
import argparse
import subprocess


def create_ssh_agent():
    p = subprocess.Popen('ssh-agent -s',
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         shell=True, universal_newlines=True)
    outinfo, errinfo = p.communicate('ssh-agent cmd\n')
    # print(outinfo)

    lines = outinfo.split('\n')
    for line in lines:
        # trim leading and trailing whitespace
        line = line.strip()
        # ignore blank/empty lines
        if not line:
            continue
        # break off the part before the semicolon
        left, right = line.split(';', 1)
        if '=' in left:
            # get variable and value, put into os.environ
            varname, varvalue = left.split('=', 1)
            print("setting variable from ssh-agent:", varname, "=", varvalue)
            os.environ[varname] = varvalue


if __name__ == "__main__":

    script_dir = os.getcwd()

    parser = argparse.ArgumentParser(
        description='Auxiliary executor for parallel programs running inside (Singularity) container under PBS.')
    parser.add_argument('-i', '--image', type=str,
                        help='Singularity SIF image or Docker image (will be converted to SIF)')
    parser.add_argument('-n', '--ncpus', type=str,
                        help='number of parallel processes')
    parser.add_argument('-B', '--bind', type=str, metavar="PATH,...", default="", required=False,
                        help='comma separated list of paths to be bind to Singularity container')
    parser.add_argument('-m', '--mpiexec', type=str, metavar="PATH", default="", required=False,
                        help="path (inside the container) to mpiexec to be run, default is 'mpiexec'")
    parser.add_argument('prog', nargs="+", help='program to be run and all its arguments')

    # create the parser for the "prog" command
    # parser_prog = parser.add_subparsers().add_parser('prog', help='program to be run and all its arguments')
    # parser_prog.add_argument('args', nargs="+", help="all arguments passed to 'prog'")

    # parser.print_help()
    # parser.print_usage()
    args = parser.parse_args()

    # get program and its arguments, set absolute path
    prog_args = args.prog
    prog_args[0] = os.path.abspath(prog_args[0])

    # get program and its arguments, set absolute path
    image = os.path.abspath(args.image)

    print("Hostname: ", os.popen('hostname').read())

    ###################################################################################################################
    # Process node file and setup ssh access to given nodes.
    ###################################################################################################################

    # get nodefile, copy it to local dir so that it can be passed into container mpiexec later
    orig_node_file = os.environ['PBS_NODEFILE']
    node_file = os.path.join(script_dir, os.path.basename(orig_node_file))
    shutil.copy(orig_node_file, node_file)
    # TODO - testing case
    # node_file = "hostfile_11184572.meta-pbs.metacentrum.cz"

    # Get ssh keys to nodes and append it to $HOME/.ssh/known_hosts
    ssh_known_hosts_to_append = []
    assert 'HOME' in os.environ
    ssh_known_hosts_file = os.path.join(os.environ['HOME'], '.ssh/known_hosts')
    # TODO - testing case
    # ssh_known_hosts_file = 'known_hosts'
    with open(ssh_known_hosts_file, 'r') as fp:
        ssh_known_hosts = fp.readlines()

    with open(node_file) as fp:
        node_names = fp.read().splitlines()
    for node in node_names:
        # touch all the nodes, so that they are accessible also through container
        os.popen('ssh ' + node + ' exit')
        # add the nodes to known_hosts so the fingerprint verification is skipped later
        # in shell just append # >> ~ /.ssh / known_hosts
        # or sort by 3.column in shell: 'sort -k3 -u ~/.ssh/known_hosts' and rewrite
        ssh_keys = os.popen('ssh-keyscan -H ' + node) .readlines()
        ssh_keys = list((line for line in ssh_keys if not line.startswith('#')))
        for sk in ssh_keys:
            splits = sk.split(" ")
            if splits[2] in ssh_known_hosts:
                ssh_known_hosts_to_append.append(sk)

    with open(ssh_known_hosts_file, 'a') as fp:
        fp.writelines(ssh_known_hosts_to_append)

    # print(os.environ)
    create_agent = 'SSH_AUTH_SOCK' not in os.environ
    if not create_agent:
        create_agent = os.environ['SSH_AUTH_SOCK'] == ''

    create_ssh_agent()
    assert 'SSH_AUTH_SOCK' in os.environ
    assert os.environ['SSH_AUTH_SOCK'] != ""

    ###################################################################################################################
    # Create Singularity container commands.
    ###################################################################################################################
    # A] process bindings, exclude ssh agent in launcher bindings
    bindings = "-B " + os.environ['SSH_AUTH_SOCK']
    # possibly add current dir to container bindings
    # bindings = bindings + "," + script_dir + ":" + script_dir
    bindings_in_launcher = ""
    if args.bind != "":
        bindings = bindings + "," + args.bind
        bindings_in_launcher = "-B " + args.bind

    sing_command = ' '.join(['singularity', 'exec', bindings, image])
    sing_command_in_launcher = ' '.join(['singularity', 'exec', bindings_in_launcher, image])

    print('sing_command:', sing_command)
    print('sing_command_in_ssh:', sing_command_in_launcher)

    # B] prepare node launcher script
    launcher_path = os.path.join(script_dir, "launcher.sh")
    launcher_lines = [
        '#!/bin/bash',
        '\n',
        'echo $(hostname) >> launcher.log',
        'echo $(pwd) >> launcher.log',
        'echo $@ >> launcher.log',
        'echo "singularity container: $SINGULARITY_NAME" >> launcher.log',
        '\n',
        'ssh $1 $2 ' + sing_command_in_launcher + ' ${@:3}',
    ]
    with open(launcher_path, 'w') as f:
        f.write('\n'.join(launcher_lines))
    os.popen('chmod +x ' + launcher_path)

    # C] set mpiexec path inside the container
    # if container path to mpiexec is provided, use it
    # otherwise try to use the default
    mpiexec_path = "mpiexec"
    if args.mpiexec != "":
        mpiexec_path = args.mpiexec

    # test_mpiexec = os.popen(sing_command + ' which ' + 'mpiexec').read()
    # # test_mpiexec = os.popen('singularity exec docker://flow123d/geomop:master_8d5574fc2 which flow123d').read()
    # print("test_mpiexec: ", test_mpiexec)
    # if mpiexec_path == "":
    #     raise Exception("mpiexec path '" + mpiexec_path + "' not found in container!")

    # D] join mpiexec arguments
    mpiexec_args = " ".join([mpiexec_path, '-f', node_file, '-launcher-exec', launcher_path, '-n', args.ncpus])

    # F] join all the arguments into final singularity container command
    final_command = " ".join([sing_command, mpiexec_args, *prog_args])

    ###################################################################################################################
    # Final call.
    ###################################################################################################################
    print(final_command)
    os.system(final_command)
