"""
Custom XEP-0077 Registration Client

Uses raw TCP/TLS sockets and manual XML handling to avoid fighting with
ClientXMPP's baked-in SASL authentication.

This is a minimal XMPP stream implementation ONLY for registration.
"""

import logging
import asyncio
import ssl
import socket
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from typing import Optional, Dict, Any, Tuple
import base64
import uuid

logger = logging.getLogger('drunk-xmpp.xep-0077')


async def _resolve_xmpp_server(domain: str) -> Tuple[str, int]:
    """
    Resolve XMPP server using SRV records.

    Returns:
        Tuple of (host, port)
    """
    # Try SRV lookup for client connections
    srv_record = f"_xmpp-client._tcp.{domain}"

    try:
        # Try aiodns if available
        try:
            import aiodns
            resolver = aiodns.DNSResolver()
            result = await resolver.query(srv_record, 'SRV')
            if result:
                # Sort by priority and weight
                result = sorted(result, key=lambda x: (x.priority, -x.weight))
                host = result[0].host.rstrip('.')
                port = result[0].port
                logger.info(f"SRV lookup: {srv_record} -> {host}:{port}")
                return host, port
        except ImportError:
            logger.debug("aiodns not available, using socket.getaddrinfo")
            pass

        # Fallback to getaddrinfo (doesn't do SRV but better than nothing)
        logger.debug(f"Using direct connection to {domain}:5222")
        return domain, 5222

    except Exception as e:
        logger.debug(f"SRV lookup failed: {e}, using default {domain}:5222")
        return domain, 5222


class RegistrationClient:
    """
    Minimal XMPP client for registration only - uses raw TCP/TLS.

    This bypasses ClientXMPP entirely to avoid authentication issues.
    """

    def __init__(self, server: str, proxy_settings: Optional[Dict[str, Any]] = None):
        """
        Initialize registration client.

        Args:
            server: XMPP server address (e.g., 'xmpp.earth')
            proxy_settings: Optional proxy configuration dict with keys:
                - proxy_type: 'socks5' or 'http'
                - proxy_host: Proxy server hostname
                - proxy_port: Proxy server port
                - proxy_username: Optional username for auth
                - proxy_password: Optional password for auth
        """
        self.server = server
        self.proxy_settings = proxy_settings
        self.reader = None
        self.writer = None
        self.connected = False
        self.form_response = None  # Preserved form from query
        self.stream_id = None

        # Build proxy URL if proxy is configured
        self.proxy_url = None
        if proxy_settings:
            self._build_proxy_url()

    async def connect(self, timeout: float = 15.0) -> Dict[str, Any]:
        """
        Connect to server and establish XMPP stream.

        Returns:
            dict: {'success': bool, 'error': str or None}
        """
        result = {'success': False, 'error': None}

        try:
            # DNS SRV lookup
            host, port = await _resolve_xmpp_server(self.server)

            logger.info(f"Connecting to {host}:{port} (for {self.server})...")

            # Establish TCP connection (with proxy support if configured)
            if self.proxy_settings:
                # Connect through proxy
                sock = await self._connect_via_proxy(host, port, timeout)
                self.reader, self.writer = await asyncio.open_connection(sock=sock)
                logger.debug(f"TCP connection established via {self.proxy_settings.get('proxy_type', 'proxy')}")
            else:
                # Direct connection
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=timeout
                )
                logger.debug("TCP connection established")

            # Start XMPP stream
            await self._send_stream_header()

            # Read stream response and features
            stream_features = await self._read_stream_features(timeout=timeout)

            if stream_features is None:
                result['error'] = "Failed to receive stream features"
                return result

            # Check if STARTTLS is required
            starttls = stream_features.find('.//{urn:ietf:params:xml:ns:xmpp-tls}starttls')
            if starttls is not None:
                logger.debug("Starting TLS...")
                await self._start_tls(timeout=timeout)

                # Re-establish stream after TLS
                await self._send_stream_header()
                stream_features = await self._read_stream_features(timeout=timeout)

                if stream_features is None:
                    result['error'] = "Failed to receive stream features after TLS"
                    return result

            self.connected = True
            result['success'] = True
            logger.info(f"Connected to {self.server} (stream ready for registration)")

        except asyncio.TimeoutError:
            result['error'] = f"Connection timeout (>{timeout}s)"
            logger.error(result['error'])
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Connection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())

        return result

    async def _send_stream_header(self):
        """Send XMPP stream opening."""
        stream_header = (
            f"<?xml version='1.0'?>"
            f"<stream:stream to='{self.server}' "
            f"xmlns='jabber:client' "
            f"xmlns:stream='http://etherx.jabber.org/streams' "
            f"version='1.0'>"
        )
        self.writer.write(stream_header.encode('utf-8'))
        await self.writer.drain()
        logger.debug(f"Sent stream header to {self.server}")

    async def _read_stream_features(self, timeout: float = 10.0) -> Optional[ET.Element]:
        """
        Read and parse stream:features using XMLPullParser.

        Returns:
            ElementTree Element or None
        """
        try:
            parser = ET.XMLPullParser(('start', 'end'))

            async with asyncio.timeout(timeout):
                while True:
                    chunk = await self.reader.read(4096)
                    if not chunk:
                        logger.error("Connection closed while reading features")
                        return None

                    parser.feed(chunk)

                    # Process XML events
                    for event, elem in parser.read_events():
                        # Extract stream ID from opening <stream:stream> tag
                        if event == 'start' and elem.tag.endswith('stream') and self.stream_id is None:
                            self.stream_id = elem.get('id')
                            if self.stream_id:
                                logger.debug(f"Stream ID: {self.stream_id}")

                        # Return complete stream:features element
                        if event == 'end' and elem.tag.endswith('features'):
                            logger.debug("Received stream features")
                            return elem

        except asyncio.TimeoutError:
            logger.error("Timeout reading stream features")
            return None
        except Exception as e:
            logger.error(f"Error reading stream features: {e}")
            return None

    async def _start_tls(self, timeout: float = 10.0):
        """Upgrade connection to TLS."""
        # Send STARTTLS request
        starttls_request = '<starttls xmlns="urn:ietf:params:xml:ns:xmpp-tls"/>'
        self.writer.write(starttls_request.encode('utf-8'))
        await self.writer.drain()

        # Wait for proceed
        buffer = b""
        async with asyncio.timeout(timeout):
            while b'<proceed' not in buffer:
                chunk = await self.reader.read(4096)
                if not chunk:
                    raise Exception("Connection closed during STARTTLS")
                buffer += chunk

        logger.debug("Received STARTTLS proceed")

        # Get the underlying transport and protocol
        transport = self.writer.transport
        protocol = transport.get_protocol()
        loop = asyncio.get_event_loop()

        # Create SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False  # For registration, we're less strict
        ssl_context.verify_mode = ssl.CERT_NONE

        # Upgrade to TLS
        new_transport = await loop.start_tls(
            transport, protocol, ssl_context,
            server_side=False,
            server_hostname=self.server
        )

        # Update both reader and writer transports for TLS
        self.writer._transport = new_transport
        self.reader._transport = new_transport

        logger.debug("TLS handshake complete")

    async def query_form(self, timeout: float = 15.0) -> Dict[str, Any]:
        """
        Query registration form from server.

        Returns:
            dict: {
                'success': bool,
                'fields': dict or None,
                'instructions': str or None,
                'captcha_data': dict or None,
                'error': str or None
            }
        """
        result = {
            'success': False,
            'fields': None,
            'instructions': None,
            'captcha_data': None,
            'error': None
        }

        if not self.connected:
            result['error'] = "Not connected"
            return result

        try:
            # Build IQ get stanza
            iq_id = f"reg_{uuid.uuid4().hex[:8]}"
            iq_stanza = (
                f"<iq type='get' id='{iq_id}' to='{self.server}'>"
                f"<query xmlns='jabber:iq:register'/>"
                f"</iq>"
            )

            logger.info(f"Querying registration form from {self.server}...")
            self.writer.write(iq_stanza.encode('utf-8'))
            await self.writer.drain()

            # Read response
            response_xml = await self._read_iq_response(iq_id, timeout=timeout)
            if response_xml is None:
                result['error'] = "Timeout waiting for response"
                return result

            # Store for later submission
            self.form_response = response_xml

            # Parse the response
            # Find query element
            query = response_xml.find('.//{jabber:iq:register}query')
            if query is None:
                result['error'] = "Invalid response - no query element"
                return result

            # Extract instructions
            instructions_elem = query.find('.//{jabber:iq:register}instructions')
            if instructions_elem is not None and instructions_elem.text:
                result['instructions'] = instructions_elem.text

            # Parse fields
            fields = {}

            # Check for data form (XEP-0004)
            form_elem = query.find('.//{jabber:x:data}x')
            if form_elem is not None:
                # Data form present
                for field_elem in form_elem.findall('.//{jabber:x:data}field'):
                    field_var = field_elem.get('var')
                    if field_var == 'FORM_TYPE':
                        continue

                    field_type = field_elem.get('type', 'text-single')
                    field_label = field_elem.get('label', field_var)

                    # Check if required
                    required_elem = field_elem.find('.//{jabber:x:data}required')
                    field_required = required_elem is not None

                    # Get value
                    value_elem = field_elem.find('.//{jabber:x:data}value')
                    field_value = value_elem.text if value_elem is not None and value_elem.text else ''

                    fields[field_var] = {
                        'type': field_type,
                        'label': field_label,
                        'required': field_required,
                        'value': field_value
                    }

                # Extract CAPTCHA data if present
                captcha_data = self._extract_captcha(form_elem, query)
                if captcha_data:
                    result['captcha_data'] = captcha_data

            else:
                # Legacy non-form registration
                for field_name in ['username', 'password', 'email', 'name']:
                    elem = query.find(f'{{jabber:iq:register}}{field_name}')
                    if elem is not None:
                        fields[field_name] = {
                            'type': 'text-private' if field_name == 'password' else 'text-single',
                            'label': field_name.capitalize(),
                            'required': field_name in ['username', 'password'],
                            'value': ''
                        }

            result['success'] = True
            result['fields'] = fields
            logger.info(f"Form received: {len(fields)} fields")

            # Close connection after query - submit will reconnect with fresh socket
            logger.info("Closing connection after query (will reconnect for submit)")
            await self.disconnect()

        except asyncio.TimeoutError:
            result['error'] = f"Timeout (>{timeout}s)"
            logger.error(result['error'])
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Query failed: {e}")
            import traceback
            logger.error(traceback.format_exc())

        return result

    async def _read_iq_response(self, iq_id: str, timeout: float = 15.0) -> Optional[ET.Element]:
        """
        Read IQ response with matching ID using XMLPullParser.

        Returns:
            ElementTree Element or None
        """
        try:
            parser = ET.XMLPullParser(('end',))

            async with asyncio.timeout(timeout):
                while True:
                    chunk = await self.reader.read(4096)
                    if not chunk:
                        logger.error("Connection closed while reading IQ response")
                        return None

                    # Feed data to incremental parser
                    parser.feed(chunk)

                    # Check for complete elements
                    for event, elem in parser.read_events():
                        if event == 'end' and elem.tag.endswith('iq'):
                            if elem.get('id') == iq_id:
                                logger.debug(f"Received IQ response for {iq_id}")
                                return elem

        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for IQ response {iq_id}")
            return None
        except Exception as e:
            logger.error(f"Error reading IQ response: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _extract_captcha(self, form_elem, query_elem) -> Optional[Dict[str, Any]]:
        """Extract CAPTCHA data from form (XEP-0158)."""
        try:
            captcha_data = None

            # Look for ocr field (CAPTCHA answer field)
            for field_elem in form_elem.findall('.//{jabber:x:data}field'):
                field_var = field_elem.get('var', '')

                if field_var == 'ocr':
                    # CAPTCHA detected
                    captcha_data = {
                        'challenge': None,
                        'sid': None,
                        'media': []
                    }

                    # Extract media elements (try both XEP-0221 namespaces)
                    media_elems = field_elem.findall('.//{urn:xmpp:media-element}media')
                    if not media_elems:
                        media_elems = field_elem.findall('.//{urn:xmpp:media:0}media')

                    for media_elem in media_elems:
                        # Try both namespace variants for uri
                        uri_elems = media_elem.findall('{urn:xmpp:media-element}uri')
                        if not uri_elems:
                            uri_elems = media_elem.findall('{urn:xmpp:media:0}uri')

                        for uri_elem in uri_elems:
                            uri_value = uri_elem.text or ''

                            # Handle Bits of Binary (cid: URIs)
                            if uri_value.startswith('cid:'):
                                cid = uri_value[4:]

                                # Find corresponding data element
                                data_elem = query_elem.find(f".//*[@cid='{cid}']")
                                if data_elem is not None and data_elem.tag.endswith('data'):
                                    data_type = data_elem.get('type', '')
                                    data_b64 = data_elem.text or ''
                                    data_bytes = base64.b64decode(data_b64)

                                    captcha_data['media'].append({
                                        'type': data_type,
                                        'data': data_bytes,
                                        'cid': cid
                                    })

                elif field_var == 'challenge':
                    if not captcha_data:
                        captcha_data = {'challenge': None, 'sid': None, 'media': []}
                    value_elem = field_elem.find('{jabber:x:data}value')
                    captcha_data['challenge'] = value_elem.text if value_elem is not None else ''

                elif field_var == 'sid':
                    if not captcha_data:
                        captcha_data = {'challenge': None, 'sid': None, 'media': []}
                    value_elem = field_elem.find('{jabber:x:data}value')
                    captcha_data['sid'] = value_elem.text if value_elem is not None else ''

            return captcha_data

        except Exception as e:
            logger.warning(f"Failed to extract CAPTCHA: {e}")
            return None

    async def submit_registration(self, form_data: Dict[str, str], timeout: float = 20.0) -> Dict[str, Any]:
        """
        Submit registration using the preserved form.

        Args:
            form_data: Form values (username, password, ocr, etc.)

        Returns:
            dict: {
                'success': bool,
                'jid': str or None,
                'error': str or None
            }
        """
        result = {'success': False, 'jid': None, 'error': None}

        if not self.form_response:
            result['error'] = "No form queried - call query_form() first"
            return result

        username = form_data.get('username')
        password = form_data.get('password')

        if not username or not password:
            result['error'] = "Username and password required"
            return result

        # Reconnect to get fresh connection (avoids silent socket death)
        # Server may have closed connection after query, or it may timeout during user CAPTCHA solving
        logger.info("Reconnecting for registration submission (fresh socket)...")
        if self.connected:
            await self.disconnect()

        connect_result = await self.connect()
        if not connect_result['success']:
            result['error'] = f"Reconnect failed: {connect_result.get('error', 'unknown')}"
            return result

        try:
            # Build submission IQ based on original form
            query = self.form_response.find('.//{jabber:iq:register}query')

            iq_id = f"reg_submit_{uuid.uuid4().hex[:8]}"

            # Check if it was a data form or legacy
            form_elem = query.find('.//{jabber:x:data}x') if query is not None else None

            if form_elem is not None:
                # Data form submission - mirror the entire form structure from query
                # Only change: type='form' -> type='submit' and fill in values
                logger.info("Building data form submission (mirroring query)")

                import copy

                # Deep copy the entire form element to preserve all structure
                submit_form = copy.deepcopy(form_elem)

                # Change type from 'form' to 'submit'
                submit_form.set('type', 'submit')

                # Fill in values for fields where user provided data
                for field_elem in submit_form.findall('.//{jabber:x:data}field'):
                    field_var = field_elem.get('var')

                    if field_var in form_data:
                        # User provided a value for this field
                        value_elem = field_elem.find('{jabber:x:data}value')
                        if value_elem is None:
                            # Create value element if it doesn't exist
                            value_elem = ET.SubElement(field_elem, '{jabber:x:data}value')
                        # Set the value (XML escaping done by ET)
                        value_elem.text = str(form_data[field_var])

                # Build IQ with the modified form
                iq_stanza = (
                    f"<iq type='set' id='{iq_id}' to='{self.server}'>"
                    f"<query xmlns='jabber:iq:register'>"
                )

                # Register namespace to avoid prefixes in serialization
                ET.register_namespace('', 'jabber:x:data')

                # Serialize the cloned form (preserves all attributes, tags, etc.)
                form_xml = ET.tostring(submit_form, encoding='unicode')
                iq_stanza += form_xml
                iq_stanza += "</query></iq>"

            else:
                # Legacy registration (no data form)
                logger.debug("Building legacy registration submission")

                # Escape values for XML safety
                username_esc = xml_escape(username)
                password_esc = xml_escape(password)

                iq_stanza = (
                    f"<iq type='set' id='{iq_id}' to='{self.server}'>"
                    f"<query xmlns='jabber:iq:register'>"
                    f"<username>{username_esc}</username>"
                    f"<password>{password_esc}</password>"
                )

                # Add optional fields
                if 'email' in form_data:
                    email_esc = xml_escape(form_data['email'])
                    iq_stanza += f"<email>{email_esc}</email>"

                iq_stanza += "</query></iq>"

            logger.info(f"Submitting registration for {username}@{self.server}...")
            # Log the actual XML being sent
            logger.info(f"Sending registration IQ:\n{iq_stanza}")
            self.writer.write(iq_stanza.encode('utf-8'))
            await self.writer.drain()

            # Read response
            response_xml = await self._read_iq_response(iq_id, timeout=timeout)
            if response_xml is None:
                result['error'] = "Timeout waiting for response"
                return result

            # Log the response
            response_str = ET.tostring(response_xml, encoding='unicode')
            logger.info(f"Received registration response:\n{response_str}")

            # Check response type
            iq_type = response_xml.get('type')
            if iq_type == 'result':
                # Success!
                result['success'] = True
                result['jid'] = f"{username}@{self.server}"
                logger.info(f"Registration successful: {result['jid']}")
            elif iq_type == 'error':
                # Parse error
                error_elem = response_xml.find('.//error')
                if error_elem is not None:
                    # Log the full error XML for debugging
                    error_xml = ET.tostring(error_elem, encoding='unicode')
                    logger.debug(f"Error response: {error_xml}")

                    # Extract error condition and text
                    condition = None
                    error_text = None

                    for child in error_elem:
                        tag = child.tag
                        if tag.endswith('}text'):
                            error_text = child.text
                        elif tag.endswith('}'):
                            condition_name = tag.split('}')[1]
                            if condition_name != 'text':
                                condition = condition_name

                    if condition:
                        if error_text:
                            result['error'] = f"{condition}: {error_text}"
                        else:
                            result['error'] = f"{condition}"
                    elif error_text:
                        result['error'] = error_text
                    else:
                        result['error'] = "Registration failed (unknown error)"
                else:
                    result['error'] = "Registration failed (unknown error)"

                logger.error(f"Registration error: {result['error']}")

        except asyncio.TimeoutError:
            result['error'] = f"Timeout (>{timeout}s)"
            logger.error(result['error'])
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Submit failed: {e}")
            import traceback
            logger.error(traceback.format_exc())

        return result

    async def disconnect(self):
        """Disconnect from server and clear all connection state."""
        if self.writer:
            try:
                logger.info(f"Disconnecting from {self.server}")
                # Send stream closing
                self.writer.write(b'</stream:stream>')
                await self.writer.drain()
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                logger.debug(f"Disconnect error (ignored): {e}")

        # Clear all connection state
        self.connected = False
        self.reader = None
        self.writer = None
        self.stream_id = None

    def _build_proxy_url(self):
        """Build proxy URL from settings dict."""
        if not self.proxy_settings:
            return

        proxy_type = self.proxy_settings.get('proxy_type', '').lower()
        proxy_host = self.proxy_settings.get('proxy_host')
        proxy_port = self.proxy_settings.get('proxy_port')
        proxy_username = self.proxy_settings.get('proxy_username')
        proxy_password = self.proxy_settings.get('proxy_password')

        if not all([proxy_type, proxy_host, proxy_port]):
            logger.warning("Incomplete proxy settings, proxy will not be used")
            return

        # Validate proxy type
        if proxy_type not in ['http', 'socks5']:
            logger.warning(f"Unknown proxy type: {proxy_type}, proxy will not be used")
            return

        # Build proxy URL
        if proxy_username and proxy_password:
            self.proxy_url = f"{proxy_type}://{proxy_username}:{proxy_password}@{proxy_host}:{proxy_port}"
        else:
            self.proxy_url = f"{proxy_type}://{proxy_host}:{proxy_port}"

        logger.info(f"Proxy configured: {proxy_type}://{proxy_host}:{proxy_port}")

    async def _connect_via_proxy(self, dest_host: str, dest_port: int, timeout: float) -> socket.socket:
        """
        Connect to destination through proxy and return socket.

        Args:
            dest_host: Destination XMPP server host
            dest_port: Destination XMPP server port
            timeout: Connection timeout

        Returns:
            Connected socket object
        """
        try:
            from python_socks.async_.asyncio import Proxy
        except ImportError:
            raise ImportError("python-socks library required for proxy support. Install with: pip install python-socks[asyncio]")

        if not self.proxy_url:
            raise RuntimeError("Proxy URL not configured")

        logger.debug(f"Connecting to {dest_host}:{dest_port} via proxy {self.proxy_url}...")

        # Create proxy object from URL
        proxy = Proxy.from_url(self.proxy_url)

        # Connect through proxy with timeout
        sock = await asyncio.wait_for(
            proxy.connect(dest_host=dest_host, dest_port=dest_port),
            timeout=timeout
        )

        logger.debug(f"Proxy tunnel established to {dest_host}:{dest_port}")
        return sock
