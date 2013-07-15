#!/usr/bin/python -tt
# A library for accessing and working with EC2.
# Authors: Jay Greguske  <jgregusk@redhat.com>,
#          Andrew Thomas <anthomas@redhat.com>
#

import logging
import os
import re
from socket import gethostname
import subprocess
import sys
import time

try:
    import boto
    from boto.ec2.connection import EC2Connection
    from boto.ec2.blockdevicemapping import EBSBlockDeviceType, BlockDeviceMapping
except ImportError:
    raise Fedora_EC2Error('Boto is not installed')

format_error = """
Image name does not match expected format. It must match one of these formats
below, and note that hyphens are the delimiter:
  Platform-PlatVersion-Arch-I
  Platform-PlatVersion-Spin-Arch-I
  Platform-PlatVersion-Spin-SpinVersion-Arch-I

A correct example would be:
  Fedora-16-i386-4

But not:
  Fedora-17-Neat-Product-2.0-x86_64-3 (too many hyphens)
  Fedora-15-i386-4-sda (same problem; get -sda out of your filename)

We're smart enough to drop the .raw if you are using the filename, which is the
default behavior. If you do not like using the filename, you can use --name to
forcibly set the name to parse. Do not include .raw if you use --name."""

def check_name(name):
    """verify the name of the image matches expectations"""
    return re.match(r'(?P<plat>[^-]+)-(?P<platver>[^-]+)-(?:(?P<prod>[^-]+)-(?:(?P<prodver>[^-]+)-)?)?(?P<arch>[^-]+)-(?P<i>\d+)$', name)


#
# Classes
#

class Fedora_EC2Error(Exception):
    """Custom exception for this library"""
    pass

class EC2Obj(object):
    """
    An object that encapsulates useful information that is specific to RCM's
    EC2 infrastructure and environments. Provides many methods to interact
    with EC2 in a standarized way.
    """    
    _instances = 1
    _devs = {}
    _devs.update([('/dev/sd' + chr(i), None) for i in range(104, 111)])

    def __init__(self, region='US', cred=None, quiet=False, logfile=None, 
                 debug=False):
        """
        Constructor; useful options to the object are interpreted here.
        EC2Objs are region specific and we want to support a script
        instanciating multiple EC2Objs, so some identity management and cross-
        object data is maintained as class variables. EC2Objs are NOT
        serialized!

        cred: a valid EC2Cred object
        quiet: Do not print to stdout
        logfile: path to write the log for use of this object
        debug: enable debug output
        """
        # logging
        format = logging.Formatter("[%(asctime)s %(name)s %(levelname)s]: %(message)s")
        if logfile == None:
            logfile = '%s.%s.log' % (__name__, EC2Obj._instances)
        logname = os.path.basename(logfile)
        if logname.endswith('.log'):
            logname = logname[:-4]
        logdir = os.path.dirname(logfile)
        if logdir != '' and not os.path.exists(logdir):
            os.makedirs(logdir)
        if os.path.exists(os.path.join(logdir,logname+'.log')):
            os.remove(os.path.join(logdir,logname+'.log'))
        self.logger = logging.getLogger(logname)
        if debug == 'True': 
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
        file_handler = logging.FileHandler(logfile)
        file_handler.setFormatter(format)
        self.logger.addHandler(file_handler)
        if not quiet == 'True':
            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setFormatter(format)
            self.logger.addHandler(stdout_handler)

        # object initialization
        if os.path.exists('/etc/boto.cfg'):
            self.conn = EC2Connection()
        else:
            Fedora_EC2Error('No boto.cfg file')
        self.region = self.alias_region(region)
        regionconn = self.conn.get_all_regions(self.region)
        self.conn = EC2Connection(region=regionconn[0])
        self.rurl = 'http://ec2.%s.amazonaws.com' % self.region
        self.logger.debug('Region: %s' % self.region)
        self.def_zone = '%sa' % self.region
        self.def_group = 'Default'
        self.id = EC2Obj._instances
        self._att_devs = {}
        self.logger.debug('Initialized EC2Obj #%s' % EC2Obj._instances)
        EC2Obj._instances += 1


    def alias_region(self, reg):
        """
        EC2 tools are not consistent about region labels, so we try to be 
        friendly about that here.
        """
        region = reg
        if reg in ('US', 'us-east'):
            region = 'us-east-1'
        elif reg == 'us-west':
            region = 'us-west-1'
        elif reg in ('EU', 'eu-west'):
            region = 'eu-west-1'
        elif reg == 'ap-southeast':
            region = 'ap-southeast-1'
        elif reg == 'ap-northeast':
            region = 'ap-northeast-1'
        elif reg in ('us-east-1', 'us-west-1', 'eu-west-1', 'ap-southeast-1',
                     'ap-northeast-1', 'us-west-2', 'sa-east-1'):
            # these are what we want, do nothing
            pass
        else:
            self.logger.warn('Unrecognized region: %s' % region)
            #Set to east by default
            region = 'us-east-1'
        return region

    def ami_info(self, ami_id):
        """
        Return a dictionary that describes an AMI:
        id - the AMI id
        source - the bucket/name of the AMI
        owner - account number of the owner
        status - AMI status, normally 'available'
        visibility - 'public' or 'private'
        product - products codes associated with it 
        arch - i386 or x86_64
        type - type of image ('machine', 'kernel', 'ramdisk')
        aki - the AKI ID
        ari - the ARI ID 
        snapid - snapshot id of of the EBS volume it was registered from
        """
        if not ami_id.startswith('ami-'):
            raise Fedora_EC2Error('Only an AMI ID can be passed to this method')
        info = {}

        res = self.conn.get_all_images([ami_id])[0]

        info = res.__dict__

        self.logger.debug('Retrieved image info: %s' % info)
        return info

    def deregister_ami(self, ami_id):
        """De-Register an AMI. Returns the ID of the AMI"""
        self.conn.deregister_image(ami_id, delete_snapshot=False)
        self.logger.info('De-Registered an AMI: %s' % ami_id)
        return ami_id

    def start_ami(self, ami, aki=None, ari=None, wait=False, zone=None,
                  group=None, keypair=None, disk=True):
        """
        Start the designated AMI. This function does not guarantee success. See
        inst_info to verify an instance started successfully. 
        Optionally takes a few keyword arguments:
            - wait: True if we should wait until the instance is running
            - aki: the AKI id to start with. None will boot it with the 
                   default it was bundled with.
            - ari: the ARI id to start with
            - zone: the availability zone to start in
            - group: the security group to start the instance in
            - keypair: SSH key pair to log in with
        Returns a dictionary describing the instance, see inst_info().
        """
        ami_info = self.ami_info(ami)
        if zone == None:
            zone = self.def_zone
        if group == None:
            group = self.def_group
        if keypair == None:
            self.logger.warning('No keypair') 
        if ami_info['architecture'] == 'i386':
            size = 'm1.small'
        elif ami_info['architecture'] == 'x86_64':
            size = 'm1.small'
        else:
            self._log_error('Unsupported arch: %s' % ami_info['architecture'])

        reservation = self.conn.run_instances(ami, instance_type=size, key_name=keypair,
                placement=zone, security_groups=group, kernel_id=aki)
        instance = reservation.instances[0]

        if wait:
            info = self.wait_inst_status(instance.id, 'running')
        else:
            info = self.inst_info(instance.id)
        self._att_devs[info['id']] = EC2Obj._devs.copy()
        self.logger.info('Started an instance of %s: %s' % (ami, instance.id))
        return info

    def inst_info(self, inst_id):
        """
        Return information about an instance. Returns a dictionary:
            id - The instance ID
            ami - The AMI ID
            group - the Security Group it booted with
            account - the account number the instance belongs to
            reservation - the reservation number for the resources
            status - instance status (pending, running, terminated, etc)
            keypair - the SSH keypair
            index
            type - the instance type string such as m1.large
            zone - availability zone
            aki - the AKI ID it is booting with
            ari - the ARI ID it is booting with 
            time - the time the instance was started
            url - the url/hostname of the instance
            address - the IP address
        """
        info = {}
        info2 = {}
        reservation = self.conn.get_all_instances([inst_id])
        inst_info = reservation[0].instances[0]
        info = reservation.__dict__
        info2 = inst_info.__dict__
        info.update(info2)

        self.logger.debug('Retrieved instance info: %s' % info)
        return info

    def get_url(self, id):
        """Return the URL address of a running instance"""
        info = self.inst_info(id)

        if info['dns_name'] == '':
            self.logger.warning('Sought URL for %s but it is not defined' % id)
        return info['dns_name']

    def wait_inst_status(self, instance, status, tries=0, interval=20):
        """
        Wait until an instance has the desired status. Optional arguments 
        tries and interval set how many tries and how long to wait between 
        polls respectively. Will throw an error if the status is ever 
        terminated, unless that is the desired status. Setting tries to 0 means
        to try forever. Returns a dictionary describing the instance, see
        inst_info().
        """
        reservation = self.conn.get_all_instances([instance])
        instance = reservation[0].instances[0]

        forever = False
        if tries == 0:
            forever = True
        timer = 1
        while timer <= tries or forever:

            if instance.update() == status:
                info = self.inst_info(instance.id)
                return info
            if instance.update() == 'terminated':
                self._log_error('%s is in the terminated state!' % instance.id)
            self.logger.info('Try #%s: %s is not %s, sleeping %s seconds' %
                (timer, instance.id, status, interval))
            time.sleep(interval)
            timer += 1
        self._log_error('Timeout exceeded for %s to be %s' % (instance.id, status))


    def _take_dev(self, inst_id, vol_id):
        """
        Internal method to get the next available device name to use when
        attaching an EBS volume to an instance. Throws an error if we have
        run out, 10 is the max.
        """
        if self._att_devs.get(inst_id) == None:
            self._att_devs[inst_id] = EC2Obj._devs.copy()
        try:
            dev = [d for d in self._att_devs[inst_id].keys() 
                if self._att_devs[inst_id][d] == None].pop()
        except IndexError:
            self._log_error('No free device names left for %s' % inst_id)
        self._att_devs[inst_id][dev] = vol_id
        self.logger.debug('taking %s to attach %s to %s' % 
            (dev, vol_id, inst_id))
        return dev


    def _release_dev(self, inst_id, vol_id):
        """
        Internal method to release a device name back into the pool when
        detaching from an instance. Throws an error if the device is already
        unattached, since this should never happen.
        """
        if vol_id not in self._att_devs[inst_id].values():
            self._log_error('Device is not attached! (%s from %s)' %
                (vol_id, inst_id))
        dev = [d for d in self._att_devs[inst_id].keys()
            if self._att_devs[inst_id][d] == vol_id].pop()
        self._att_devs[inst_id][dev] = None
        self.logger.debug('releasing %s from %s for %s' %
            (dev, inst_id, vol_id))
        return dev


    def create_vol(self, size, zone=None, wait=False, snap=None):
        """
        Create an EBS volume of the given size in region/zone. If size == 0,
        do not explicitly set a size; this may be useful with "snap", which
        creates a volume from a snapshot ID.
        
        This function does not guarantee success, you should check with
        vol_available() to ensure it was created successfully. If wait is set
        to True, we will wait for the volume to be available before returning;
        returns a dictionary describing the volume, see vol_info().
        """
        if zone == None:
            zone = self.def_zone
        if size == 0 and snap == None:
            raise Fedora_EC2Error('No size or snapshot defined')
        volume = self.conn.create_volume(size, zone, snapshot=snap)
        if wait:
            info = self.wait_vol_status(volume.id, 'available')
        else:
            info = self.vol_info(volume.id)
        self.logger.info('Created an EBS volume: %s' % volume.id)
        return info

    def attach_vol(self, inst_id, vol_id, wait=False, dev=None):
        """
        Attach an EBS volume to an AMI id in region. This is not an immediate 
        action, you should check the status of the volume (see vol_info) if
        you wish to do somethiFng more with it after attaching. Setting wait to
        True cause the method to wait until the volume is attached before
        returning. Can can be used to manually set the device name, otherwise
        one will be selected automatically. Returns a dictionary describing the
        volume, see vol_info().
        """
        if dev == None:
            dev = self._take_dev(inst_id, vol_id)
        else:
            if not dev.startswith('/dev/sd'):
                self._log_error('Not a valid device name: %s' % dev)
        check = self.conn.get_all_volumes([vol_id])[0]
        if check.status == 'in-use':
            raise Fedora_EC2Error('Volume is already attached')
        self.conn.attach_volume(vol_id, inst_id, dev)
        if wait:
            info = self.wait_vol_attach_status(vol_id, 'attached')
        else:
            info = self.vol_info(vol_id)
        self.logger.info('attached %s to %s' % (vol_id, inst_id))
        return info

    def detach_vol(self, inst_id, vol_id, wait=False):
        """
        Detach an EBS volume from an instance. Note that this action is not
        immediate, you should check the status of the volume if you wish to do
        something more with it after detaching (see vol_info). Setting wait to
        True will make the method wait until the volume is detached before
        returning. Returns a dictionary describing the volume, see vol_info().
        """
        self.conn.detach_volume(vol_id, inst_id)
        if wait:
            info = self.wait_vol_attach_status(vol_id, None)
        else:
            info = self.vol_info(vol_id)
        self._release_dev(inst_id, vol_id)
        self.logger.info('Detached %s from %s' % (vol_id, inst_id))
        return info

    def vol_info(self, id):
        """
        Get status on a volume. Returns a dictionary with the following fields:
        id - the volume ID
        size - the size in gigabytes of the volume
        snapshot
        zone - availability zone
        status - available, creating, ...
        time - the time the volume was created

        If the volume is attached, additional fields will be available:
        instance - the instance ID it is attached to
        device - the device name it is exposed as
        attach_status - status of the attachment
        attach_time - when the volume was attached
        """
        info = {}
        if not id.startswith('vol-'):
            raise Fedora_EC2Error('Only a VOL ID can be passed to this method')
        vol = self.conn.get_all_volumes([id])[0]
        info = vol.__dict__

        if vol.status == 'in-use':

            info['instance'] = str(vol.attach_data.instance_id)
            info['device'] = str(vol.attach_data.device)
            while str(vol.attach_data.status) != 'attached':
                vol.update()
            info['attach_status'] = str(vol.attach_data.status)
            info['attach_time'] = str(vol.attach_data.attach_time)

        self.logger.debug('Retrieved volume info: %s' % info)
        return info

    def wait_vol_status(self, vol_id, status, tries=0, interval=20):
        """
        Wait until a volume has the desired status. Optional arguments tries 
        and interval set how many tries and how long to wait between polls 
        respectively. Will throw a RuntimeError if the status is ever 
        'deleting', unless that is the desired status. Setting tries to 0 means
        to try forever. Returns a dictionary describing the volume, see
        vol_info().
        """
        vol = self.conn.get_all_volumes([vol_id])[0]
        forever = False
        if tries == 0:
            forever = True
        timer = 1

        while timer <= tries or forever:
            if vol.update() == status:
                info = self.vol_info(vol_id)
                return info
            if vol.update() == 'deleting':
                raise RuntimeError, '%s is being deleted!' % vol.id
            self.logger.info('Try #%s: %s not %s, sleeping %s seconds' %
                (timer, vol_id, status, interval))
            time.sleep(interval)
            timer += 1
        self._log_error('Timeout exceeded waiting for %s to be %s' %
            (vol_id, status))

    def wait_vol_attach_status(self, vol_id, status, tries=0, interval=10):
        """
        Wait until a volume has the desired status. Optional arguments tries 
        and interval set how many tries and how long to wait between polls 
        respectively. Setting tries to 0 means to try forever. Returns a 
        dictionary describing the volume, see vol_info().
        """
        vol = self.conn.get_all_volumes([vol_id])[0]
        forever = False
        if tries == 0:
            forever = True
        timer = 1
        print_status = status
        if status == None:
            print_status = 'Detached'
        while timer <= tries or forever:
            vol.update()
            if vol.attachment_state() == status:
                info = self.vol_info(vol_id)
                return info
            self.logger.info('Try #%s: %s not %s, sleeping %s seconds' %
                (timer, vol_id, print_status, interval))
            time.sleep(interval)
            timer += 1
        self._log_error('Timeout exceeded waiting for %s to be %s' %
            (vol_id, status))

    def take_snap(self, vol_id, wait=False):
        """
        Snapshot a detached volume, returns the snapshot ID. If wait is set to
        True, return once the snapshot is created. Returns a dictionary 
        that describes the snapshot.
        """
        vol = self.conn.get_all_volumes([vol_id])[0]
        snap = vol.create_snapshot([vol_id])
        if wait:
            info = self.wait_snap_status(snap.id, 'completed')
        else:
            info = self.snap_info(snap.id)
        self.logger.info('snapshot %s taken' % snap.id)
        return info

    def snap_info(self, snap_id):
        """
        Return a dictionary that describes a snapshot:
        id - the snapshot ID
        vol_id - the volume ID the snapshot was taken from
        status - pending, completed, etc
        time - when the snapshot was created
        """
        info = {}
        snaps = self.conn.get_all_snapshots([snap_id])[0]
        info = snaps.__dict__

        self.logger.debug('Retrieved snapshot info: %s' % info)
        return info

    def wait_snap_status(self, snap_id, status, tries=0, interval=20):
        """
        Wait until a snapshot is completes. Optional arguments tries and
        interval set how many tries and how long to wait between polls
        respectively. Setting tries to 0 means to try forever. Returns nothing.
        """
        snap = self.conn.get_all_snapshots([snap_id])[0]
        forever = False
        if tries == 0:
            forever = True
        timer = 1
        while timer <= tries or forever:
            snap.update()
            if snap.status == status:
                info = self.snap_info(snap_id)
                return info
            self.logger.info('Try #%s: %s is not %s, sleeping %s seconds' %
                (timer, snap_id, status, interval))
            time.sleep(interval)
            timer += 1
        self._log_error('Timeout exceeded for %s to be %s' % (snap_id, status))

    def register_snap(self, snap_id, arch, name, aki=None, desc=None, ari=None,
                      pub=True, disk=False):
        """
        Register an EBS volume snapshot as an AMI. Returns the AMI ID. An arch,
        snapshot ID, and name for the AMI must be provided. Optionally
        a description, AKI ID, ARI ID and billing code may be specified too.
        disk is whether or not we are registering a disk image.
        """
        self.logger.info('Registering snap: %s' % (snap_id))
        snap = self.conn.get_all_snapshots([snap_id])[0]
        #Makes block device map
        ebs = EBSBlockDeviceType()
        ebs.snapshot_id = snap_id
        block_map = BlockDeviceMapping()
 
        if aki == None:
            raise Fedora_EC2Error('Need to specify an AKI')  
        if disk:
            disk = '/dev/sda=%s' % snap_id
            root = '/dev/sda'
        else:
            disk = '/dev/sda1=%s' % snap_id
            root = '/dev/sda1'
        block_map[root] = ebs

        ami_id = self.conn.register_image(name=name, description=desc,
              image_location = '', architecture=arch, kernel_id=aki, 
              ramdisk_id=ari,root_device_name=root, block_device_map=block_map)

        if not ami_id.startswith('ami-'):
            self._log_error('Could not register an AMI')
        self.logger.info('Registered an AMI: %s' % ami_id)
        return ami_id

    def delete_snap(self, snap_id):
        """
        USE WITH CAUTION!
        Delete an EBS volume snapshot. Returns the ID of the snapshot that was
        deleted.
        """
        del_snap = self.conn.delete_snapshot(snap_id)
        self.logger.info('Deleted a snapshot: %s' % snap_id)
        return snap_id

    def delete_vol(self, vol_id):
        """
        USE WITH CAUTION!

        Delete an EBS volume. If snapshotted already it is safe to do this.
        Returns the id of the volume that was deleted.
        """
        self.conn.delete_volume(vol_id)
        self.logger.info('Deleted a volume: %s' % vol_id)
        return vol_id

    def kill_inst(self, inst_id, wait=False):
        """
        USE WITH CAUTION!
        
        Kill a running instance. Returns a dictionary describing the instance,
        see inst_info for more information. Setting wait=True means we will not
        return until the instance is terminated.
        """
        self.conn.terminate_instances([inst_id])
        if wait:
            inst_info = self.wait_inst_status(inst_id, 'terminated')
        else:
            inst_info = self.inst_info(inst_id)
        self.logger.info('Killed an instance: %s' % inst_id)
        return inst_info

    def make_public(self, ami):
        """
        Make an AMI publicly launchable. Should be used for Hourly images only!
        """
        self.conn.modify_image_attribute(ami, attribute='launchPermission',
            operation='add', user_ids=None, groups=['all']) 
        self.logger.info('%s is now public!' % ami)

    def get_my_insts(self):
        """
        Return a list of dicts that describe all running instances this account
        owns. See inst_info for a description of the dict.
        """
        mine = []
        instances = self.conn.get_all_instances()
        info = {}
        info2 = {}
        for inst in instances:
            data = inst.instances[0]
            info = inst.__dict__
            info2 = data.__dict__
            info.update(info2)
            mine.append(info)
            info = {}
            info2 = {}
            self.logger.debug('Retrieved instance info: %s' % info)
        return mine

    def get_my_amis(self):
        """
        Return a list of dicts that describe all AMIs this account owns. See
        ami_info for a description of the dict; there is one difference though.
        The snapid field may contain a list of snapshots in the blockmapping
        for an image. It does not take just the first one.
        """
        image_list = self.conn.get_all_images(owners='self')       

        mine = []
        info = {'snapid': []}
        for image in image_list: 
            info = image.__dict__
            if info.get('id') != None and info.get('id').startswith('ami-'):
                # we don't want AKIs or ARIs
                mine.append(info.copy())
                info = {'snapid': []}
        self.logger.debug(str(mine))
        return mine

    def get_my_snaps(self):
        """
        Return a list of dicts that describe all snapshots owned by this
        account. See snap_info for a description of the dict.
        """
        all_snaps = self.conn.get_all_snapshots(owner='self')
        mine = []
        for snap in all_snaps:
            info = {}
            info = snap.__dict__
            mine.append(info.copy())
        self.logger.debug('Retrieved my snapshots: %s' % mine)
        return mine

    # utility methods

    def run_cmd(self, cmd, retry=3):
        """
        Run a command and collect the output and return value.
        """
        self.logger.debug('Command: %s' % cmd)
        while retry > -1:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, shell=True)
            ret = proc.wait()
            output = proc.stdout.read().strip()
            self.logger.debug('Return code: %s' % ret)
            self.logger.debug('Output: %s' % output)
            if ret != 0:
                self.logger.error('Command had a bad exit code: %s' % ret)
                self.logger.error('Command run: %s' % cmd)
                self.logger.error('Output:\n%s' % output)
                self.logger.info('%s retries left, sleeping...' % retry)
                retry -= 1
                if retry < 0:
                    raise Fedora_EC2Error('Command failed, see logs for output')
                time.sleep(10)
            else:
                self.logger.debug('command successful')
                retry = -1
        return output, ret


    def _log_error(self, msg):
        """report and throw an error"""
        self.logger.error(msg)
        raise Fedora_EC2Error(msg)

    # SSH-specific methods

    def get_ssh_opts(self, path=None):
        """return ssh options we want to use throughout this script"""
        if path != None:
            if os.path.exists(path):
                kp = path
            else:
                raise Fedora_EC2Error('Key path does not exist')
        else:
            raise Fedora_EC2Error('No path specified') 
        ssh_opts = '-i %s ' % kp + \
                   '-o "StrictHostKeyChecking no" ' + \
                   '-o "PreferredAuthentications publickey"'
        return ssh_opts

    def run_ssh(self, instance, cmd, path=None):
        """ssh to an instance and run a command"""
        ssh_opts = self.get_ssh_opts(path)
        ssh_host = 'root@%s' % str(instance['dns_name'])
        return self.run_cmd('ssh %s %s "%s"' % (ssh_opts, ssh_host, cmd),
            retry=0)

    def wait_ssh(self, instance, tries=15, interval=20, path=None):
        """
        Continually attempt to ssh into an instance and return when we can.
        This useful for when an instance is booting and we have to wait until
        ssh is available. Default timeout is 5 minutes.
        """
        forever = False
        if tries == 0:
            forever = True
        timer = 1
        while timer <= tries or forever:
            try:
                return self.run_ssh(instance, 'true', path)
            except Fedora_EC2Error:
                self.logger.warning('SSH failed, sleeping for %s seconds' %
                    interval)
                time.sleep(interval)
                timer += 1
        raise Fedora_EC2Error('Could not SSH in after %s tries' % tries)

