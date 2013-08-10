#!/usr/bin/python -tt
# Upload images to EBS volumes in EC2 in all regions
# Authors: Jay Greguske <jgregusk@redhat.com>,
#          Andrew Thomas <anthomas@redhat.com>
#          Sam Kottler <shk@redhat.com>
#

import logging
import math
import ConfigParser
from optparse import OptionParser
import os
import subprocess
import sys
import threading

import fedora_ec2

#
# Constants
#

results = {}
result_lock = threading.Lock()
mainlog = None
opts = None

#
# Functions
#

def get_options():
    usage = """
    Create EBS-backed AMI from a disk image. The process begins by starting an
    instance creating an EBS volume and attaching it. The disk image is then
    dd'ed to the EBS volume on the instance over ssh. That volume is snapshoted
    and then registered as a new AMI. This script is threaded; one thread for
    each region we want to upload to. Usually, image file names are of the form:
    Fedora-Release-VariantName-Arch.raw

    Usage: %prog [options] path-to-image"""
    parser = OptionParser(usage=usage)
    parser.add_option('-a', '--all', help='Upload to all regions',
        action='store_true', default=False)
    parser.add_option('-c', '--config', help='Add a config file',
        default=['/etc/uploader.conf'], action='append')
    parser.add_option('-e', '--description', default=None,
        help='Give a description of this image'),
    parser.add_option('-k', '--keep', help='Keep tmp instance/volumes around',
        action='store_true', default=False)
    parser.add_option('-n', '--name', default=False,
        help='Override the image name. The default is the disk image name.')
    parser.add_option('-r', '--region', action='append', default=[], dest='regions',
        help='Only upload to a specific region. May be used more than once.')
    parser.add_option('-s', '--size', type='int', default=0,
        help='Customize size of image')
    global opts
    opts, args = parser.parse_args()
    if len(args) != 1:
        parser.error('Please specify a path to an image')
    image = args[0]
    parse_config()
    if not os.path.exists(image):
        parser.error('Could not find an image to upload at %s' % image)
    size = os.stat(image).st_size
    if os.getuid() != 0:
        parser.error('You have to be root to upload a partition image')
    size = int(math.ceil(size / 1024.0 / 1024.0 / 1024.0))
    if opts.size != 0:
        if opts.size <= size:
            parser.error('Can only make size larger, not smaller.')
    else:
        opts.size = size
    if not opts.name:
        if not image.endswith('.raw'):
            parser.error('Not a .RAW file')
        opts.name = os.path.basename(image)[:-4] # chop off .raw
    m = fedora_ec2.check_name(opts.name)
    if not m:
        parser.error(fedora_ec2.format_error)

    if m.group('arch') not in (
        'i386',
        'x86_64'
        'sparc',
        's390'
    ):
        parser.error('The arch must be i386 or x86_64')
    opts.matcher = m
    return opts, image

def setup_log():
    """set up the main logger"""
    global mainlog
    format = logging.Formatter("[%(asctime)s %(name)s %(levelname)s]: %(message)s")
    logname = 'upload'
    logdir = get_opt('logdir')
    if not os.path.exists(logdir):
        os.makedirs(logdir)
    #Theres a way to do this I think through the logging module
    if os.path.exists(os.path.join(logdir, logname + '.log')):
        os.remove(os.path.join(logdir, logname + '.log'))
    mainlog = logging.getLogger(logname)
    if get_opt('debug') == 'True':
        mainlog.setLevel(logging.DEBUG)
    else:
        mainlog.setLevel(logging.INFO)
    file_handler = logging.FileHandler(os.path.join(logdir, logname + '.log'))
    file_handler.setFormatter(format)
    mainlog.addHandler(file_handler)
    if not get_opt('quiet') == 'True':
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(format)
        mainlog.addHandler(stdout_handler)

def parse_config():
    config = ConfigParser.ConfigParser()
    success = config.read(opts.config)
    if len(success) == 0:
        raise fedora_ec2.Fedora_EC2Error('Could not parse a config file!')
    if len(config.defaults()) == 0:
        raise fedora_ec2.Fedora_EC2Error('Config file has no DEFAULT section')
    if len(opts.regions) == 0:
        opts.regions = config.sections()
    # XXX: global mutator
    opts.config = config

def get_opt(name, region='DEFAULT'):
    """
    Return a region specific option, if it is defined, otherwise take the
    default.
    """
    answer = None
    try:
        answer = opts.config.get(region, name)
    except ConfigParser.NoOptionError:
        try:
            answer = opts.config.get('DEFAULT', name)
        except ConfigParser.NoOptionError:
            raise fedora_ec2.Fedora_EC2Error('No option defined: %s' % name)
    return answer


def run_cmd(cmd, wait=True):
    """run an external command"""
    mainlog.debug('Command: %s' % cmd)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, shell=True)
    if not wait:
        return
    ret = proc.wait()
    output = proc.stdout.read().strip()
    mainlog.debug('Return code: %s' % ret)
    mainlog.debug('Output: %s' % output)
    if ret != 0:
        mainlog.error('Command had a bad exit code: %s' % ret)
        mainlog.error('Command run: %s' % cmd)
        mainlog.error('Output:\n%s' % output)
        raise fedora_ec2.Fedora_EC2Error('Command failed, see logs for output')
    return output, ret

def upload_region(region, image_path):
    """Upload an image to a region"""
    # start the Stager instance
    ec2 = fedora_ec2.EC2Obj(region=region, debug=get_opt('debug'),
        logfile=os.path.join(get_opt('logdir'), 'upload-%s.log' % region),
        quiet=get_opt('quiet'))
    mainlog.info('beginning process for %s to %s' % (image_path, ec2.region))
    if get_opt('avail_zone', region) == '':
        zone = ec2.region
    else:
        zone = ec2.region+get_opt('avail_zone', region)
    inst_info = ec2.start_ami(get_opt('stage_ami', region), zone=zone,
        group=get_opt('sec_group',region).split(','),
        keypair=get_opt('sshkey',region), wait=True)

    # create and attach volumes
    mainlog.info('[%s] creating EBS volume we will snapshot' % ec2.region)
    ebs_vol_info = ec2.create_vol(opts.size, wait=True, zone=zone)
    ebs_vol_info = ec2.attach_vol(inst_info['id'], ebs_vol_info['id'],
        wait=True)

    # prep the temporary volume and upload to it
    ec2.wait_ssh(inst_info, path=get_opt('sshpath', region))
    mainlog.info('[%s] uploading image %s to EBS volume %s' %
        (ec2.region, image_path, ebs_vol_info['device']))
    run_cmd('dd if=%s bs=4096 | ssh %s -C root@%s "dd of=%s bs=4096"' %
        (image_path, ec2.get_ssh_opts(path=get_opt('sshpath', region)), inst_info['dns_name'],
        ebs_vol_info['device']))

    # detach the two EBS volumes, snapshot the one we dd'd the disk image to,
    # and register it as an AMI
    ec2.detach_vol(inst_info['id'], ebs_vol_info['id'], wait=True)
    snap_info = ec2.take_snap(ebs_vol_info['id'], wait=True)
    AMI_ID = ec2.register_snap(snap_info['id'], opts.matcher.group('arch'),
            opts.name, aki=get_opt('aki', region), desc=opts.description)

    # grant access to the new AMIs
    mainlog.info('[%s] granting access to the AMI(s)' % ec2.region)
    ID = get_opt('ids', region)
    if ID == '':
        raise fedora_ec2.Fedora_EC2Error('Insert AWS IDs or "public"')
    elif ID == 'public':
        ec2.make_public(AMI_ID)
        mainlog.info('Making public')
    else:
        ID = ID.split(',')
        ec2.grant_access(AMI_ID, ID)

    # cleanup
    if not opts.keep:
        mainlog.info('[%s] cleaning up' % ec2.region)
        ec2.delete_vol(ebs_vol_info['id'])
        ec2.kill_inst(inst_info['id'])
    mainlog.info('%s is complete' % ec2.region)
    mainlog.info('[%s] Cloud AMI ID: %s' % (ec2.region, AMI_ID))

    # maintain results
    result_lock.acquire()
    results[AMI_ID] = 'Cloud Access offering in %s for %s' %\
            (ec2.region, opts.matcher.group('arch'))
    result_lock.release()

if __name__ == '__main__':
    opts, ipath = get_options()
    setup_log()

    threads = []

    for region in opts.regions:
        mainlog.info('spawning thread for %s' % region)
        threads.append(threading.Thread(target=upload_region,
            args=(region, ipath), name=region))

    for t in threads:
        t.start()
    for t in threads:
        t.join()
    mainlog.info('Results of all uploads follow this line\n')
    mainlog.info('\n'.join(['%s : %s' % (k, v) for k, v in results.items()]))

    #This is to broadcast new AMI's
    import fedmsg
    for k,v in results.items():
        fedmsg.publish(topic='image.ec2.complete', modname='cloud-image-uploader', msg={'%s  : %s' % (k,v)})

