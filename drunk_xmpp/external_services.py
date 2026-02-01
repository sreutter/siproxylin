"""
XEP-0215: External Service Discovery
Queries XMPP server for STUN/TURN credentials for WebRTC calls.
"""

import logging
from typing import List, Dict, Optional


class ExternalServicesMixin:
    """
    Mixin for XEP-0215: External Service Discovery.
    Allows clients to discover STUN/TURN servers with credentials from XMPP server.
    """

    async def get_external_services(self, service_type: Optional[str] = None) -> List[Dict]:
        """
        Query XMPP server for external services (STUN/TURN servers).

        Args:
            service_type: Optional filter ('stun', 'turn', 'turns'). None = all types.

        Returns:
            List of service dicts with keys:
                - type: 'stun', 'turn', or 'turns'
                - host: Server hostname
                - port: Server port
                - transport: 'udp' or 'tcp' (for TURN)
                - username: Username for authentication (if provided)
                - password: Password for authentication (if provided)
                - expires: Expiration timestamp (optional)

        Example response from server (XEP-0215):
            <services xmlns='urn:xmpp:extdisco:2'>
              <service type='stun' host='stun.example.com' port='3478'/>
              <service type='turn' host='turn.example.com' port='3478'
                       username='user' password='pass' transport='udp'/>
            </services>
        """
        if not self.is_connected():
            self.logger.warning("Cannot query external services: not connected")
            return []

        try:
            from xml.etree.ElementTree import Element

            # Build XEP-0215 query
            iq = self.make_iq_get()
            iq['to'] = self.boundjid.domain  # Query our own server

            # Try XEP-0215 v2 first (urn:xmpp:extdisco:2)
            services_elem = Element('{urn:xmpp:extdisco:2}services')
            if service_type:
                services_elem.set('type', service_type)
            iq.append(services_elem)

            self.logger.info(f"Querying server for external services (type={service_type})")

            # Send IQ and wait for response (10s timeout)
            result = await iq.send(timeout=10)

            # Parse response
            services = []
            services_elem = result.xml.find('{urn:xmpp:extdisco:2}services')

            if services_elem is None:
                # Try XEP-0215 v1 (urn:xmpp:extdisco:1) as fallback
                services_elem = result.xml.find('{urn:xmpp:extdisco:1}services')

            if services_elem is None:
                self.logger.info("Server does not support XEP-0215 (External Service Discovery)")
                return []

            # Parse each service entry
            for service in services_elem:
                service_data = {
                    'type': service.get('type'),
                    'host': service.get('host'),
                    'port': int(service.get('port', 3478)),
                }

                # Optional attributes
                if service.get('transport'):
                    service_data['transport'] = service.get('transport')
                if service.get('username'):
                    service_data['username'] = service.get('username')
                if service.get('password'):
                    service_data['password'] = service.get('password')
                if service.get('expires'):
                    service_data['expires'] = service.get('expires')

                services.append(service_data)

                # Log (mask password)
                log_data = service_data.copy()
                if 'password' in log_data:
                    log_data['password'] = '***'
                self.logger.debug(f"Discovered service: {log_data}")

            self.logger.info(f"Discovered {len(services)} external service(s)")
            return services

        except Exception as e:
            self.logger.error(f"Failed to query external services: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return []

    def format_ice_servers(self, services: List[Dict]) -> List[Dict]:
        """
        Convert XEP-0215 service list to WebRTC ICE server format.

        Args:
            services: List from get_external_services()

        Returns:
            List of ICE server dicts compatible with WebRTC/GStreamer:
                [
                    {"urls": ["stun:stun.example.com:3478"]},
                    {"urls": ["turn:turn.example.com:3478?transport=udp"],
                     "username": "user", "credential": "pass"}
                ]
        """
        ice_servers = []

        for service in services:
            service_type = service.get('type')
            host = service.get('host')
            port = service.get('port', 3478)

            if not service_type or not host:
                continue

            # Build URL
            if service_type == 'stun':
                url = f"stun:{host}:{port}"
                ice_servers.append({"urls": [url]})

            elif service_type in ['turn', 'turns']:
                transport = service.get('transport', 'udp')
                url = f"{service_type}:{host}:{port}?transport={transport}"

                ice_entry = {"urls": [url]}
                if service.get('username'):
                    ice_entry['username'] = service['username']
                if service.get('password'):
                    ice_entry['credential'] = service['password']

                ice_servers.append(ice_entry)

        return ice_servers
