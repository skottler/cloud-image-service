import fedmsg.consumers
import fedmsg
import datanommer.models
import upload_image

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
            upload_image.main(message)



