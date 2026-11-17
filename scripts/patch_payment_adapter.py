#!/usr/bin/env python3
"""Update payment_adapters.py to add Mercado Pago return URLs configuration."""

import os

FILE_PATH = "C:/Users/KABUM/Desktop/Servi-os-Marketplace-Engenharia-de-Software-main/payment_adapters.py"

# Read the current file
with open(FILE_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# Find the old MercadoPagoAdapter class
old_class_start = content.find("class MercadoPagoAdapter(GatewayAdapter):")
old_class_start = content.find("\n", old_class_start)

# Find the end of the class (GATEWAY_ADAPTERS = {})
old_class_end = content.find("GATEWAY_ADAPTERS = {}")

if old_class_start == -1 or old_class_end == -1:
    print("ERROR: Could not find class boundaries")
    print(f"old_class_start: {old_class_start}")
    print(f"old_class_end: {old_class_end}")
else:
    # Extract the old class
    old_class = content[old_class_start:old_class_end].strip()
    
    # New class to replace
    new_class = '''class MercadoPagoAdapter(GatewayAdapter):
    """Mercado Pago payment gateway adapter.

    Supports both legacy Payments API and Checkout Pro Orders API.
    Return URLs are configured per order via config_return_urls().
    """

    def __init__(self):
        self.access_token = MERCADOPAGO_ACCESS_TOKEN
        self.base_url = 'https://api.mercadopago.com/v1'
        # Checkout Pro Orders API endpoint
        self.orders_url = 'https://api.mercadopago.com/v1/orders'
        # Return URLs configuration (set via config_return_urls)
        self.config = {
            'success_url': None,
            'failure_url': None,
            'pending_url': None,
            'auto_return': 'approved',  # 'approved' or 'all'
        }

    def config_return_urls(self, success_url=None, failure_url=None, pending_url=None, auto_return='approved'):
        """Configure the return URLs for Checkout Pro Orders.

        Args:
            success_url: URL redirecionado quando o pagamento é aprovado.
            failure_url: URL redirecionado quando o pagamento é rejeitado.
            pending_url: URL redirecionado quando o pagamento está pendente.
            auto_return: 'approved' para aprovação só, 'all' para qualquer resultado.
        """
        if success_url:
            self.config['success_url'] = success_url
        if failure_url:
            self.config['failure_url'] = failure_url
        if pending_url:
            self.config['pending_url'] = pending_url
        if auto_return in ('approved', 'all'):
            self.config['auto_return'] = auto_return
        return self.config

    def get_return_urls_config(self):
        """Get the configured return URLs for the current order."""
        return {
            'success_url': self.config['success_url'],
            'failure_url': self.config['failure_url'],
            'pending_url': self.config['pending_url'],
            'auto_return': self.config['auto_return'],
        }

    def create_charge(self, user_id, amount, currency='BRL', metadata=None, use_orders_api=True):
        """Create a payment in Mercado Pago.

        Args:
            user_id: User ID making the payment.
            amount: Amount in BRL.
            currency: Currency code (default 'BRL').
            metadata: Additional metadata.
            use_orders_api: If True, use Checkout Pro Orders API (recommended);
                            if False, use legacy Payments API.

        Returns:
            dict: Payment confirmation or error.
        """
        if not self.access_token:
            return {'error': 'Mercado Pago not configured', 'code': 'MISSING_CREDENTIALS'}

        # Format amount for Mercado Pago (in cents)
        amount_cents = int(round(amount * 100)) if amount > 0 else 100

        if use_orders_api:
            return self._create_order(user_id, amount_cents, currency, metadata)
        else:
            return self._create_payment(user_id, amount_cents, currency, metadata)

    def _create_payment(self, user_id, amount_cents, currency, metadata):
        """Create a payment using the legacy Payments API (older integration)."""
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

        payload = {
            'transaction_amount': amount_cents,
            'currency_id': currency,
            'description': 'Pagamento de serviço',
            'payer': {
                'id': user_id
            },
            'metadata': {
                'user_id': str(user_id)
            }
        }

        if metadata:
            payload['metadata'].update(metadata)

        try:
            req = Request(
                f'{self.base_url}/payments',
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return {
                    'id': result.get('id'),
                    'status': result.get('status'),
                    'payment_type': result.get('payment_type'),
                    'transaction_amount': result.get('transaction_amount'),
                    'point_of_interaction': {
                        'id': result.get('point_of_interaction', {}).get('id')
                    } if result.get('point_of_interaction') else None,
                    'date_created': result.get('date_created')
                }
        except HTTPError as e:
            return {'error': f'Mercado Pago HTTP error: {e.code}', 'code': 'HTTP_ERROR'}
        except URLError as e:
            return {'error': f'Mercado Pago connection error: {e.reason}', 'code': 'CONNECTION_ERROR'}
        except Exception as e:
            return {'error': str(e), 'code': 'UNKNOWN_ERROR'}

    def _create_order(self, user_id, amount_cents, currency, metadata):
        """Create an order using the Checkout Pro Orders API (recommended).

        Configures return URLs per the Mercado Pago documentation:
        https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-orders/web-integration/configure-back-urls
        """
        if not self.access_token:
            return {'error': 'Mercado Pago not configured', 'code': 'MISSING_CREDENTIALS'}

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'X-Idempotency-Key': f'order_{user_id}_{int(time.time())}'
        }

        # Configure the online config with return URLs
        online_config = {
            'success_url': self.config.get('success_url'),
            'failure_url': self.config.get('failure_url'),
            'pending_url': self.config.get('pending_url'),
            'auto_return': self.config.get('auto_return'),
        }

        payload = {
            'type': 'online',
            'processing_mode': 'manual',
            'total_amount': amount_cents,
            'currency_id': currency,
            'description': 'Pagamento de serviço',
            'payer': {
                'id': user_id
            },
            'external_reference': f'order_{user_id}_{int(time.time())}',
            'config': {
                'online': {k: v for k, v in online_config.items() if v is not None}
            }
        }

        if metadata:
            payload['metadata'] = metadata

        try:
            req = Request(
                self.orders_url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return {
                    'id': result.get('id'),
                    'status': result.get('status'),
                    'payment_type': result.get('payment_type'),
                    'total_amount': result.get('total_amount'),
                    'currency_id': result.get('currency_id'),
                    'point_of_interaction': {
                        'id': result.get('point_of_interaction', {}).get('id')
                    } if result.get('point_of_interaction') else None,
                    'date_created': result.get('date_created'),
                    'return_urls': result.get('return_url') or self.config
                }
        except HTTPError as e:
            return {'error': f'Mercado Pago HTTP error: {e.code}', 'code': 'HTTP_ERROR'}
        except URLError as e:
            return {'error': f'Mercado Pago connection error: {e.reason}', 'code': 'CONNECTION_ERROR'}
        except Exception as e:
            return {'error': str(e), 'code': 'UNKNOWN_ERROR'}

    def get_payment_status(self, gateway_payment_id):
        """Get payment status from Mercado Pago."""
        if not self.access_token:
            return {'error': 'Mercado Pago not configured'}

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

        try:
            req = Request(
                f'{self.base_url}/payments/{gateway_payment_id}',
                headers=headers,
                method='GET'
            )
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return {
                    'id': result.get('id'),
                    'status': result.get('status'),
                    'payment_type': result.get('payment_type'),
                    'transaction_amount': result.get('transaction_amount'),
                    'capture': result.get('capture', False)
                }
        except Exception as e:
            return {'error': str(e), 'code': 'UNKNOWN_ERROR'}

    def refund(self, gateway_payment_id, amount=None):
        """Refund a payment in Mercado Pago."""
        if not self.access_token:
            return {'error': 'Mercado Pago not configured'}

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

        data = {'amount': amount} if amount else {}

        try:
            req = Request(
                f'{self.base_url}/payments/{gateway_payment_id}/refunds',
                data=json.dumps(data).encode('utf-8') if data else b'',
                headers=headers,
                method='POST'
            )
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return {
                    'id': result.get('id'),
                    'status': result.get('status'),
                    'amount': result.get('amount') if not amount else amount,
                    'currency': 'BRL'
                }
        except Exception as e:
            return {'error': str(e), 'code': 'UNKNOWN_ERROR'}

    def validate_webhook(self, payload, signature):
        """Validate Mercado Pago webhook signature.

        Mercado Pago uses the X-Signature header with the format:
        'type=NOTIFICATION_TYPE, timestamp=TIMESTAMP, token=TOKEN, signature=SIGNATURE'

        Args:
            payload: The raw webhook payload.
            signature: The X-Signature header value.

        Returns:
            bool: True if valid, False otherwise.
        """
        if not self.access_token:
            return True  # Skip verification in dev mode
        # Placeholder - implement full verification against Mercado Pago docs
        # in production (see https://www.mercadopago.com.br/developers/pt/docs/notifications/payment/notifications)
        return True

    def format_gateway_response(self, gateway_response):
        """Format response for internal use."""
        return {
            'gateway': 'mercadopago',
            'gateway_id': gateway_response.get('id'),
            'status': gateway_response.get('status'),
            'total_amount': gateway_response.get('total_amount'),
            'currency_id': gateway_response.get('currency_id'),
            'payment_type': gateway_response.get('payment_type'),
            'point_of_interaction': gateway_response.get('point_of_interaction'),
            'date_created': gateway_response.get('date_created'),
            'success': gateway_response.get('status') in ('approved', 'paid')
        }

'''
    
    # Check if old class exists
    if old_class in content:
        print("Old class found. Replacing...")
        # Replace old class with new class
        new_content = content.replace(old_class, new_class)
        
        # Write the updated file
        with open(FILE_PATH, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print("File updated successfully")
        
        # Verify
        with open(FILE_PATH, 'r', encoding='utf-8') as f:
            new_content_check = f.read()
        
        if "config_return_urls" in new_content_check:
            print("✓ config_return_urls method found")
        if "orders_url" in new_content_check:
            print("✓ orders_url found")
        if "use_orders_api" in new_content_check:
            print("✓ use_orders_api parameter found")
    else:
        print("ERROR: Old class not found in file")
        print(f"Length of old class: {len(old_class)}")
