import fedora_ec2
import os
import subprocess
import sys 



def get_options():
    usage = """
    Removes old AMIs that are no longer needed.

    Usage: %prog [options] AMI ID"""
    parser = OptionParser(usage=usage)
    parser.add_option('-t', '--time', help='Timeframe to remove?',
        default=False, action='store_true')
    global opts
    opts, args = parser.parse_args()
    return

def setup_log():
    """set up the main logger"""
    global mainlog
    format = logging.Formatter("[%(asctime)s %(name)s %(levelname)s]: %(message)s")
    logname = 'takedown'
    logdir = get_opt('logdir')
    if not os.path.exists(logdir):
        os.makedirs(logdir)
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

def take_down(region):
    ec2 = fedora_ec2.EC2Obj(region=region, debug=get_opt('debug'),
        logfile=os.path.join(get_opt('logdir'), 'upload-%s.log' % region),
        quiet=get_opt('quiet'))
    mainlog.info('beginning process for %s to %s' % (image_path, ec2.region))
    if get_opt('avail_zone', region) == '':
        zone = ec2.region
    else:
        zone = ec2.region+get_opt('avail_zone', region)
    #MAKE LIST OF AMI's TO TAKE DOWN
    #need some sort of identifier
    destroyed =[]
    for ami in ami_list:
        destroyed.append(ec2.deregister_ami(ami))
    return destroyed

if __name__ == '__main__':
    opts = get_options()
    setup_log()

    threads = []

    for region in opts.regions:
        mainlog.info('spawning thread for %s' % region)
        threads.append(threading.Thread(target=take_down,
            args=(region), name=region))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

