"""
Copyright (c) 2015 SONATA-NFV
ALL RIGHTS RESERVED.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Neither the name of the SONATA-NFV [, ANY ADDITIONAL AFFILIATION]
nor the names of its contributors may be used to endorse or promote
products derived from this software without specific prior written
permission.

This work has been performed in the framework of the SONATA project,
funded by the European Commission under Grant number 671517 through
the Horizon 2020 and 5G-PPP programmes. The authors would like to
acknowledge the contributions of their colleagues of the SONATA
partner consortium (www.sonata-nfv.eu).
"""

import logging
import yaml
import time
import sys
import _thread
import websocket

from sonsmbase.smbase import sonSMbase
from threading import Thread
from websocket_server import WebsocketServer
from json import loads, dumps

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger("ssm-task_config-1")
LOG.setLevel(logging.DEBUG)
logging.getLogger("son-mano-base:messaging").setLevel(logging.INFO)


class Server():

    def __init__(self):

        self.ssm = None

    # Called for every client connecting (after handshake)
    def new_client(self, client, server):
        logging.warning("*********************"+"New client connected and was given id"+ str(client['id']))

    # Called for every client disconnecting
    def client_left(self, client, server):
        logging.warning("*********************"+"Client("+str(client['id'])+") disconnected")

    def message_received(self, client, server, message):
        LOG.info('message received...')
        if len(message) > 200:
            message = message[:200]+'..'
        logging.warning("*********************"+"Client("+str(client['id'])+") said:"+message)

        # Format message
        messageDict = loads(message)
        actionName = messageDict['name']
        message = {}

        LOG.info("Creating messages for the SSM plugin")
        # Translating the portal application message into the right format for
        # the SSM.
        if actionName == "basic":
            message['chain'] = ['vpn-vnf', 'tor-vnf']

        if actionName == "anon":
            message['chain'] = ['vpn-vnf', 'prx-vnf', 'tor-vnf']

        # Only when the status of the service is ready is it allowed to make
        # a reconfiguration request. Possible status: 'configuring', 'instantiating'
        # or 'ready'
        LOG.info("Checking if service is ready to be reconfigured")
        status = self.ssm.get_status()

        # Requesting the reconfiguration. This method has no response. get_status
        # should be fetched (see above) to determine when the reconfiguration is
        # finished.
        if status == 'ready':
            LOG.info("Triggering plugin SSM to reconfigure")
            self.ssm.push_update(message)
            # TODO: fetch get_status until 'ready', before sending response to portal
            # application
        else:
            LOG.info("Service not ready to be reconfigured, status: " + str(status))
            # TODO: respond to portal that service is not ready to reconfigure

    def add_ssm(self, ssm_object):
        """
        By adding the Config SSM, the server/client can trigger SSM methods
        directly.
        """
        self.ssm = ssm_object

    def connect_to_socket(self, port, host):
        # TODO: How to connect to the portal application? Should we make the SSM
        # the client and the application the server?
        LOG.info("connecting to socket...")
        logging.warning("*********************Listening to Requests...!")
        port = port
        host = host
        # host="selfservice-ssm"
        server = WebsocketServer(port, host=host)
        server.set_fn_new_client(self.new_client)
        server.set_fn_client_left(self.client_left)
        server.set_fn_message_received(self.message_received)
        server.run_forever()


class TaskConfigMonitorSSM(sonSMbase):

    def __init__(self, server=None):

        """
        :param specific_manager_type: specifies the type of specific manager that could be either fsm or ssm.
        :param service_name: the name of the service that this specific manager belongs to.
        :param function_name: the name of the function that this specific manager belongs to, will be null in SSM case
        :param specific_manager_name: the actual name of specific manager (e.g., scaling, placement)
        :param id_number: the specific manager id number which is used to distinguish between multiple SSM/FSM
        that are created for the same objective (e.g., scaling with algorithm 1 and 2)
        :param version: version
        :param description: description
        """
        self.specific_manager_type = 'ssm'
        self.service_name = 'psaservice'
        self.specific_manager_name = 'task-config-monitor'
        self.id_number = '1'
        self.version = 'v0.1'
        self.counter = 0

        # init SSM
        self.nsd = None
        self.nsr = None
        self.functions = {}
        self.vnfrs = []
        self.ingress = None
        self.egress = None
        self.ip_mapping = None
        self.status = 'instantiating'
        self.chain = ''

        self.description = "Task - Config SSM for the PSA."

        # Connect with server
        # LOG.info("Connecting to server")
        # self.server = server
        # self.server.add_ssm(self)
        # port = 4000
        # host = "10.30.0.116"
        # Thread(target=self.server.connect_to_socket(port, host)).start()

        super(self.__class__, self).__init__(specific_manager_type= self.specific_manager_type,
                                             service_name= self.service_name,
                                             specific_manager_name = self.specific_manager_name,
                                             id_number = self.id_number,
                                             version = self.version,
                                             description = self.description)

    def on_registration_ok(self):
        LOG.info("Received registration ok event.")
        self.manoconn.publish(topic='specific.manager.registry.ssm.status', message=yaml.dump(
                                  {'name':self.specific_manager_id,'status': 'UP and Running'}))

        # Subscribe to the topic that the SLM will be sending on
        topic = 'generic.ssm.' + self.sfuuid
        self.manoconn.subscribe(self.received_request, topic)

        # Subscribe to a topic to emulate portal behavior
        topic = 'emulate.portal'
        self.manoconn.subscribe(self.emulate_portal, topic)

    def received_request(self, ch, method, prop, payload):
        """
        This method is called when the SLM is reaching out
        """
        content = yaml.load(payload)

        # Don't react to self-sent messages
        if prop.app_id == self.specific_manager_id:
            LOG.info("Received self-sent message, ignoring...")
            return

        # Don't react to messages that are not a request
        if 'ssm_type' not in content.keys():
            LOG.info("Received message that is not a request, ignoring...")
            return

        if str(content['ssm_type']) == 'task':
            LOG.info("Received a task request")
            self.task_request(prop.correlation_id, content)
            return

        if str(content['ssm_type']) == 'configure':
            LOG.info("Received a configure request")
            self.configure_request(prop.correlation_id, content)
            return

        if str(content['ssm_type']) == 'monitor':
            LOG.info("Received a monitor request")
            self.monitor_request(prop.correlation_id, content)
            return

        # If the request type field doesn't match any of the above
        LOG.info("type " + str(content['ssm_type']) + " not covered by SSM")

    def task_request(self, corr_id, content):
        """
        This method handles a task request. A task request allows the SSM to
        change the tasks in the workflow of the SLM. For the vPSA, we wan to
        add a configuration phase: first we want to dictate the payload for the
        configration FSMs and then we want to trigger there config_event.
        """

        # Update the received schedule
        schedule = content['schedule']

        schedule.insert(7, 'vnfs_config')
        schedule.insert(7, 'configure_ssm')
        schedule.append('inform_config_ssm')

        response = {'schedule': schedule, 'status': 'COMPLETED'}

        LOG.info("task request responded to: " + str(response))

        # Sending a response
        topic = 'generic.ssm.' + self.sfuuid
        self.manoconn.notify(topic,
                             yaml.dump(response),
                             correlation_id=corr_id)

    def configure_request(self, corr_id, content):
        """
        This method handles a configuration request. If the configuration
        request is made during the instantiation workflow, it means that
        the SSM needs to configure which VNF requires a config_event, and
        what the required payload is.
        """

        if 'ip_mapping' in content.keys():
            LOG.info("Ip mapping found, saving...")
            self.ip_mapping = content['ip_mapping']

        if content["workflow"] == 'instantiation':
            msg = "Received a configure request for the instantiation workflow"
            LOG.info(msg)
            self.status = 'configuring'
            self.configure_instantiation(corr_id, content)

        if content["workflow"] == 'reconfigure':
            msg = "Received a configure request for the reconfigure workflow"
            LOG.info(msg)
            self.status = 'configuring'
            self.configure_reconfigure(corr_id)

        if content["workflow"] == 'status':
            msg = "Received a configure status update"
            LOG.info(msg)
            self.status = content['status']
            LOG.info("status: " + str(self.status))

#            time.sleep(10)
#            LOG.info("Done sleeping")
#            payload = {}
#            payload['chain'] = ['vpn-vnf']
#             self.push_update(payload)

    def configure_instantiation(self, corr_id, content):
        """
        This method creates the configure response for the instantiation
        workflow. It will set the trigger for a config_event for each VNF.
        The payload for the config_event is the generic one provided by the
        SP.
        """
        LOG.info("Configuration instantiation request: " + str(content))

        service = content['service']
        functions = content['functions']

        self.nsd = service['nsd']
        self.nsr = service['nsr']

        for function in functions:
            LOG.info("Adding vnf: " + str(function['vnfd']['name']))
            self.functions[function['vnfd']['name']] = {}
            self.functions[function['vnfd']['name']]['id'] = function['id']
            self.functions[function['vnfd']['name']]['vnfd'] = function['vnfd']
            self.functions[function['vnfd']['name']]['vnfr'] = function['vnfr']
            if function['vnfd']['name'] == 'prx-vnf':
                self.functions[function['vnfd']['name']]['configuration_opt'] = 'transparent'
            self.vnfrs.append(function['vnfr'])

            vdu = function['vnfr']['virtual_deployment_units'][0]
            cps = vdu['vnfc_instance'][0]['connection_points']

            for cp in cps:
                if cp['type'] in ['internal', 'external']:
                    if cp['id'] in ['in', 'inout']:
                        own_ip = cp['interface']['address']
                    if cp['id'] in ['out']:
                        output_ip = cp['interface']['address']
                        self.functions[function['vnfd']['name']]['output_ip'] = output_ip

                if cp['type'] in ['management']:
                    management_ip = cp['interface']['address']

            self.functions[function['vnfd']['name']]['own_ip'] = own_ip
            self.functions[function['vnfd']['name']]['management_ip'] = management_ip
            self.functions[function['vnfd']['name']]['next_ip'] = None

            LOG.info("own_ip: " + str(own_ip))

        self.ingress = content['ingress']
        self.egress = content['egress']

        # Hardcode the next IPs for the instantiation
        LOG.info("keys in function: " + str(self.functions.keys()))
        for key in self.functions.keys():
            LOG.info("Function %s: %s", key, str(self.functions[key]))
            if key == 'vpn-vnf':
                if 'prx-vnf' in self.functions.keys():
                    self.functions[key]['next_ip'] = self.floating_to_internal(self.functions['prx-vnf']['own_ip'])
                elif 'tor-vnf' in self.functions.keys():
                    self.functions[key]['next_ip'] = self.floating_to_internal(self.functions['tor-vnf']['own_ip'])
                else:
                    self.functions[key]['next_ip'] = None
            if key == 'prx-vnf':
                if 'tor-vnf' in self.functions.keys():
                    self.functions[key]['next_ip'] = self.floating_to_internal(self.functions['tor-vnf']['own_ip'])
                else:
                    self.functions[key]['next_ip'] = None
            if key == 'tor-vnf':
                self.functions[key]['next_ip'] = None

        response = self.create_configuration_message()

        LOG.info("Generated response: " + str(response))
        # Sending a response
        topic = 'generic.ssm.' + self.sfuuid
        self.manoconn.notify(topic,
                             yaml.dump(response),
                             correlation_id=corr_id)

        LOG.info("status: " + str(self.status))

    def configure_reconfigure(self, corr_id):
        """
        This method reconfigures the service. This is the method that the
        Portal Application should call. The payload contains a list that
        is ordered. Each VNF is represented by its name (based on the
        descriptor)
        """

        for index in range(0, len(self.chain) - 1):
            current_vnf = self.chain[index]
            next_vnf = self.chain[index + 1]
            next_ip = self.functions[next_vnf]['own_ip']
            converted_ip = self.floating_to_internal(next_ip)
            self.functions[current_vnf]['next_ip'] = converted_ip

        last_vnf = self.chain[-1]
        self.functions[last_vnf]['next_ip'] = None

        response = self.create_configuration_message()
        LOG.info("Generated response: " + str(response))

        # Sending a response
        topic = 'generic.ssm.' + self.sfuuid
        self.manoconn.notify(topic,
                             yaml.dump(response),
                             correlation_id=corr_id)

        LOG.info("status: " + str(self.status))

    def create_configuration_message(self):
        """
        This method creates the payload for the configuration response to the
        SLM.
        """

        response = {}
        response['vnf'] = []

        for key in self.functions.keys():
            vnf = self.functions[key]
            new_entry = {}
            new_entry['id'] = vnf['id']
            payload = {}
            payload['management_ip'] = vnf['management_ip']
            payload['own_ip'] = vnf['own_ip']
            payload['next_ip'] = vnf['next_ip']
            if 'output_ip' in vnf.keys():
                payload['output_ip'] = vnf['output_ip']
            if key == 'prx-vnf':
                payload['configuration_opt'] = vnf['configuration_opt']
            new_entry['configure'] = {'trigger': True,
                                      'payload': payload}

            response['vnf'].append(new_entry)

        return response

    def floating_to_internal(self, floating_ip):
        """
        This method tries to convert a floating ip into an internal ip.
        """
        LOG.info("Mapping floating IP to internal IP")
        resulting_ip = floating_ip
        for ip_duo in self.ip_mapping:
            if ip_duo['floating_ip'] == floating_ip:
                LOG.info('Internal IP found')
                resulting_ip = ip_duo['internal_ip']
                break

        return resulting_ip

    def get_status(self):

        return self.status

    def push_update(self, content):

        self.chain = content['chain']
        if 'prx_config' in content.keys():
            new_config = content['prx_config']
            self.functions['prx-vnf']['configuration_opt'] = new_config

        self.status = 'configuring'

        message = {}
        message['workflow'] = 'reconfigure'
        message['service_instance_id'] = self.sfuuid

        payload = yaml.dump(message)

        topic = 'monitor.ssm.' + self.sfuuid
        self.manoconn.notify(topic, payload)

    def monitor_request(self, corr_id, content):
        """
        This method will be triggered when monitoring data is received.
        """
        # if 'nsd' in content.keys():
        #     LOG.info("Received descriptors")
        #     self.nsd = content['nsd']
        #     self.vnfs = content['vnfs']

        # else:
        #     if self.counter == 0:
        #         message = {}
        #         message['foo'] = 'bar'
        #         message['service_instance_id'] = self.sfuuid
        #         message['workflow'] = 'termination'

        #         # message['schedule'] = ['vnfs_scale']
        #         # message['vnf'] = []

        #         # for vnf in self.vnfs:
        #         #     if vnf['vnfd']['name'] == 'vtc-vnf':
        #         #         new_entry = {}
        #         #         new_entry['id'] = vnf['id']
        #         #         new_entry['scale'] = {'trigger': True,
        #         #                               'payload': {'foo': 'bar',
        #         #                                           'vnfr': 'bar'}}
        #         #         message['vnf'].append(new_entry)
        #         topic = 'monitor.ssm.' + self.sfuuid
        #         self.manoconn.notify(topic, yaml.dump(message))
        #         self.counter = 1
        #         LOG.info("Responded to monitoring request")

        pass

    def received_request(self, ch, method, prop, payload):
        """
        This topic processes an emulated portal press
        """

        message = yaml.load(payload)
        LOG.info("Received emulated portal request:" + str(message))

        request = {}
        request['chain'] = message['chain']
        self.push_update(request)


def main():

    portal_server = Server()
#    TaskConfigMonitorSSM(server=portal_server)
    TaskConfigMonitorSSM()

if __name__ == '__main__':
    main()
