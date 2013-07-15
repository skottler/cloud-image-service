import fedmsg.consumers
import fedmsg
import datanommer.models
import koji
import os
import shutil

DEFAULTS = {
    'datanommer.enabled': False,
    # Put a sqlite db in the current working directory if the user doesn't
    # specify a real location.
    'datanommer.sqlalchemy.url': 'sqlite:///datanommer.db',
}


import logging
log = logging.getLogger("fedmsg")


class Nommer(fedmsg.consumers.FedmsgConsumer):
    topic = "*"
    config_key = 'datanommer.enabled'

    def __init__(self, hub):
        super(Nommer, self).__init__(hub)

        # If fedmsg doesn't think we should be enabled, then we should quit
        # before setting up all the extra special zmq machinery.
        # _initialized is set in moksha.api.hub.consumer
        if not getattr(self, "_initialized", False):
            return

        # Setup a sqlalchemy DB connection (postgres, or sqlite)
        datanommer.models.init(self.hub.config['datanommer.sqlalchemy.url'])

    def consume(self, message):
        #Edited for our purposes
        log.debug("Nomming %r" % message)
        #TODO: Find/make correct topic
        if message['topic'] == 'fedoraproject.org.prod.SOMETHING':
            start_upload(message)

    def start_upload(self, message):
        #The message should have a koji task ID, from that we can get some data
        taskID = message
        conn = koji.ClientSession('http://koji.fedoraproject.org/kojihub')
        task = conn.getTaskInfo(taskID, request=True)
        #Convert from qcow2 to raw
        if location.endswith('.qcow2'):
            newLocation = location[:6] + '.raw'
            os.system('qemu-img convert %s %s' % (location, (newLocation)))
        os.system('xz -k %s' % (newLocation)) #Remove -k if do not want to keep original .raw
        #Copy file(s) to right location
        #TODO: Get correct location/credentials. Conversion can put the file in new locatation?
        """shutil.copy(newLocation, '/pub/alt/stage/19-TC2/Images/%s' % arch)"""

        #fedmsg tells that this exists
        fedmsg.publish(topic='', modname='', msg={os.path.basename(newLocation):'/pub/alt/stage/19-TC2/Images/%s' % (task['arch'])})
        os.system('python /usr/lib/python2.6/site-packages/uploading_scripts/uploader.py %s' % PATH)
        #fedmsg is inside upload.py so no need to broadcast here

        os.system('xz -k %s' % (PATH)) #Remove -k if do not want to keep original .raw
        #Move to http://alt.fedoraproject.org/pub/alt/cloud

