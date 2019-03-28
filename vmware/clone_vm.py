#!/usr/bin/env python
"""
Based on clone_vm.py by Dann Bohn
Modified by Roberto Mello <rmello@truemark.io>

Clone a VM from template
"""
from pyVmomi import vim
from pyVim.connect import SmartConnect, SmartConnectNoSSL, Disconnect
import argparse
import getpass
import sys
import yaml
import logging
from add_nic_to_vm import add_nic


def get_parser():
    """ Get parser for arguments from CLI """
    parser = argparse.ArgumentParser(
        description='Arguments for talking to vCenter')

    parser.add_argument('-y','--yaml',
                        required=False, metavar="YAML_CONFIG_FILE",
                        action='store',
                        help='YAML file with config to run with. If using this, all other command-line options are disregarded.')

    parser.add_argument('-s', '--host',
                        action='store',
                        help='vSpehre service to connect to')

    parser.add_argument('-o', '--port',
                        type=int,
                        default=443,
                        action='store',
                        help='Port to connect on')

    parser.add_argument('-u', '--user',
                        action='store',
                        help='Username to use')

    parser.add_argument('-p', '--password',
                        required=False,
                        action='store',
                        help='Password to use')

    parser.add_argument('-t', '--template',
                        action='store',
                        help='Name of the template/VM \
                            you are cloning from')

    parser.add_argument('--datacenter-name',
                        required=False,
                        action='store',
                        default=None,
                        help='Name of the Datacenter you\
                            wish to use. If omitted, the first\
                            datacenter will be used.')

    parser.add_argument('--vm-folder',
                        required=False,
                        action='store',
                        default=None,
                        help='Name of the VMFolder you wish\
                            the VM to be dumped in. If left blank\
                            The datacenter VM folder will be used')

    parser.add_argument('--datastore-name',
                        required=False,
                        action='store',
                        default=None,
                        help='Datastore you wish the VM to end up on\
                            If left blank, VM will be put on the same \
                            datastore as the template')

    parser.add_argument('--datastorecluster-name',
                        required=False,
                        action='store',
                        default=None,
                        help='Datastorecluster (DRS Storagepod) you wish the VM to end up on \
                            Will override the datastore-name parameter.')

    parser.add_argument('--cluster-name',
                        required=False,
                        action='store',
                        default=None,
                        help='Name of the cluster you wish the VM to\
                            end up on. If left blank the first cluster found\
                            will be used')

    parser.add_argument('--resource-pool',
                        required=False,
                        action='store',
                        default=None,
                        help='Resource Pool to use. If left blank the first\
                            resource pool found will be used')

    parser.add_argument('--opaque-network',
                        required=False,
                        help='Name of the opaque network to add to the VM')

    parser.add_argument('--no-ssl',
                        action='store_true',
                        help='Skip SSL verification')

    parser.add_argument('--power-on',
                        dest='power_on',
                        action='store_true',
                        help='power on the VM after creation')

    parser.add_argument('-v','--verbose',
                        action='store_true',
                        help='Log verbosely')

    parser.add_argument('--vms',
                        action='append',
                        help='Name of the VM(s) you wish to make. Repeat to\
                             pass multiple VMs to be created.')

    return parser
#end

def wait_for_task(task):
    """ wait for a vCenter task to finish """
    task_done = False
    while not task_done:
        if task.info.state == 'success':
            return task.info.result

        if task.info.state == 'error':
            logging.error(task.info.result)
            task_done = True
#end

def get_obj(content, vimtype, name):
    """
    Return an object by name, if name is None the
    first found object is returned
    """
    obj = None
    container = content.viewManager.CreateContainerView(
        content.rootFolder, vimtype, True)
    for c in container.view:
        if name:
            if c.name == name:
                obj = c
                break
        else:
            obj = c
            break

    return obj
#end

def clone_vm(
        content, template, vm_name, si,
        datacenter_name, vm_folder, datastore_name,
        cluster_name, resource_pool, power_on, datastorecluster_name):
    """
    Clone a VM from a template/VM, datacenter_name, vm_folder, datastore_name
    cluster_name, resource_pool, and power_on are all optional.
    """

    # if none, get the first one
    datacenter = get_obj(content, [vim.Datacenter], datacenter_name)

    if vm_folder:
        destfolder = get_obj(content, [vim.Folder], vm_folder)
    else:
        destfolder = datacenter.vmFolder

    if datastore_name:
        datastore = get_obj(content, [vim.Datastore], datastore_name)
    else:
        datastore = get_obj(
            content, [vim.Datastore], template.datastore[0].info.name)

    # if None, get the first one
    if not cluster_name:
        logging.warning("No cluster passed. We'll try to get the first one, but it might not work...")

    cluster = get_obj(content, [vim.ClusterComputeResource], cluster_name)

    if resource_pool:
        resource_pool = get_obj(content, [vim.ResourcePool], resource_pool)
    else:
        resource_pool = cluster.resourcePool

    vmconf = vim.vm.ConfigSpec()

    if datastorecluster_name:
        podsel = vim.storageDrs.PodSelectionSpec()
        pod = get_obj(content, [vim.StoragePod], datastorecluster_name)
        podsel.storagePod = pod

        storagespec = vim.storageDrs.StoragePlacementSpec()
        storagespec.podSelectionSpec = podsel
        storagespec.type = 'create'
        storagespec.folder = destfolder
        storagespec.resourcePool = resource_pool
        storagespec.configSpec = vmconf

        try:
            rec = content.storageResourceManager.RecommendDatastores(
                storageSpec=storagespec)
            rec_action = rec.recommendations[0].action[0]
            real_datastore_name = rec_action.destination.name
        except:
            real_datastore_name = template.datastore[0].info.name

        datastore = get_obj(content, [vim.Datastore], real_datastore_name)

    # set relospec
    relospec = vim.vm.RelocateSpec()
    relospec.datastore = datastore
    relospec.pool = resource_pool

    clonespec = vim.vm.CloneSpec()
    clonespec.location = relospec
    clonespec.powerOn = power_on

    logging.info("Cloning VM {}...".format(vm_name))
    task = template.Clone(folder=destfolder, name=vm_name, spec=clonespec)
    wait_for_task(task)
#end

def process_stanza(args):
    '''
    This was put into a function so that we could process multiple "stanzas"
    (there's probably a better name for it) of vm instantion instructions in
    the yaml file.

    However, for now this program is not doing that because we'd need logic
    to separate stanzas that succeeded and failed. Ideally it'd be atomic, but
    in order to achieve that, we'd have to remove the VMs created from
    succeeded stanzas upon hitting a failed one, and that wouldadd complexity
    we don't want at this poin"t.

    :param args: args from parser.parse_args()
    :return:
    '''
    si = None

    if args.no_ssl:
        si = SmartConnectNoSSL(
            host=args.host,
            user=args.user,
            pwd=args.password,
            port=args.port)
    else:
        si = SmartConnect(
            host=args.host,
            user=args.user,
            pwd=args.password,
            port=args.port)

    content = si.RetrieveContent()
    template = None
    template = get_obj(content, [vim.VirtualMachine], args.template)
    logging.debug(template)

    if template:
        if type(args.vms) is not list:
            vms = list(args.vms)
        else:
            vms = args.vms

        for one_vm_name in vms:
            clone_vm(
                content, template, one_vm_name, si,
                args.datacenter_name, args.vm_folder,
                args.datastore_name, args.cluster_name,
                args.resource_pool, args.power_on, args.datastorecluster_name
            )
            if args.opaque_network:
                vm = get_obj(content, [vim.VirtualMachine], one_vm_name)
                add_nic(si, vm, args.opaque_network)
    else:
        logging.ERROR("template not found")

    Disconnect(si)
#end

def main():
    parser = get_parser()
    args = parser.parse_args()

    if args.yaml:
        # we pass the parser instance here so read_yaml_config can process the
        # arguments in the YAML file through the parser, instead of trying to
        # reinvent the wheel

        with open(args.yaml, 'r') as stream:
            data_loaded = yaml.load(stream)

        new_args = []

        for (k, v) in data_loaded.items():
            # store_true options, meaning they are only True if present
            if k == 'options':
                for op in v:
                    new_args.append("--{}".format(op))
            else:
                if type(v) is list:
                    for avm in v:
                        new_args.append("--{}".format(k))
                        new_args.append(avm)
                else:
                    new_args.append("--{}".format(k))
                    new_args.append(str(v))

        args = parser.parse_args(new_args)
    #endif

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if not args.host or not args.user or not args.template or not args.vms:
        parser.print_help()
        logging.error("Required options missing from CLI or YAML: -s/--host, -u/--user, --template, -v/--vms")
        sys.exit(-1)

    if not args.password:
        args.password = getpass.getpass(
            prompt='Enter password')

    logging.debug("args: {}".format(args))

    process_stanza(args)
#end

if __name__ == "__main__":
    main()
