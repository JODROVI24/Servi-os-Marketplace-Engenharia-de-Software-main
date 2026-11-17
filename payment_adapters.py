# Payment Gateway Adapters
# PCI-DSS SAQ-A compliant: NEVER store raw PAN/CVV. Only use gateway tokens.

import hashlib
import hmac
import os
import time
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import database
from database import DBIntegrityError

# Gateway configuration (from environment variables, never hardcoded)
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
PAGSEGURO_TOKEN = os.environ.get('PAGSEGURO_TOKEN', '')
PAGSEGURO_CLIENT_ID = os.environ.get('PAGSEGURO_CLIENT_ID', '')
MERCADOPAGO_ACCESS_TOKEN = os.environ.get('MERCADOPAGO_ACCESS_TOKEN', '')

# Default gateway for development
DEFAULT_GATEWAY = 'stripe'

# Webhook signatures
def create_hmac_signature(payload, secret):
    """Create HMAC-SHA256 signature for webhook verification."""
    if not secret:
        return None
    signature = hmac.new(secret.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return signature

def verify_webhook_signature(payload, signature, secret):
    """Verify that the webhook signature matches the payload."""
    if not secret or not signature:
        return False
    expected = create_hmac_signature(payload, secret)
    return hmac.compare_digest(expected, signature)


class GatewayAdapter:
    """Abstract base class for payment gateway adapters."""

    def create_charge(self, user_id, amount, currency='BRL', metadata=None):
        """Create a charge/payment for the given user and amount."""
        raise NotImplementedError

    def get_payment_status(self, gateway_payment_id):
        """Get the current status of a payment from the gateway."""
        raise NotImplementedError

    def refund(self, gateway_payment_id, amount=None):
        """Refund a payment.
        
        Args:
            gateway_payment_id: The payment ID from the gateway.
            amount: Amount to refund (in cents for BRL). If None, full refund.
        
        Returns:
            dict: Refund confirmation or error.
        """
        raise NotImplementedError

    def get_payment(self, gateway_payment_id):
        """Get payment details from the gateway."""
        raise NotImplementedError

    def validate_webhook(self, payload, signature):
        """Validate webhook signature."""
        raise NotImplementedError


class StripeAdapter(GatewayAdapter):
    """Stripe payment gateway adapter."""

    def __init__(self):
        self.secret_key = STRIPE_SECRET_KEY
        self.webhook_secret = STRIPE_WEBHOOK_SECRET
        self.base_url = 'https://api.stripe.com/v1'
        self.charges_url = f'{self.base_url}/charges'

    def create_charge(self, user_id, amount, currency='BRL', metadata=None):
        """Create a charge in Stripe.
        
        Args:
            user_id: The user ID making the payment.
            amount: Amount in cents (e.g., 1000 = R$ 10.00).
            currency: Currency code (default 'BRL').
            metadata: Additional metadata.
        
        Returns:
            dict: Charge confirmation or error.
        """
        if not self.secret_key:
            return {'error': 'Stripe not configured', 'code': 'MISSING_CREDENTIALS'}

        # Stripe expects amounts in cents (minor units)
        # Convert BRL amount to cents (1 BRL = 100 cents)
        amount_cents = int(round(amount * 100)) if amount > 0 else 100

        headers = {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Stripe-Version': '2024-12-18'
        }

        data = {
            'amount': amount_cents,
            'currency': currency,
            'metadata[user_id]': str(user_id),
        }

        if metadata:
            for key, value in metadata.items():
                data[f'metadata[{key}]'] = str(value)

        try:
            req = Request(
                self.charges_url,
                data=urlencode(data).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return {
                    'id': result.get('id'),
                    'status': result.get('status'),
                    'amount': result.get('amount'),
                    'currency': result.get('currency'),
                    'created': result.get('created'),
                    'metadata': result.get('metadata', {})
                }
        except HTTPError as e:
            return {'error': f'Stripe HTTP error: {e.code}', 'code': 'HTTP_ERROR'}
        except URLError as e:
            return {'error': f'Stripe connection error: {e.reason}', 'code': 'CONNECTION_ERROR'}
        except Exception as e:
            return {'error': str(e), 'code': 'UNKNOWN_ERROR'}

    def get_payment_status(self, gateway_payment_id):
        """Get payment status from Stripe."""
        if not self.secret_key:
            return {'error': 'Stripe not configured'}

        headers = {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        try:
            req = Request(
                f'{self.charges_url}/{gateway_payment_id}',
                headers=headers,
                method='GET'
            )
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return {
                    'id': result.get('id'),
                    'status': result.get('status'),
                    'amount': result.get('amount'),
                    'currency': result.get('currency'),
                    'captured': result.get('captured', False),
                    'refunded': result.get('refunded', False)
                }
        except Exception as e:
            return {'error': str(e), 'code': 'UNKNOWN_ERROR'}

    def refund(self, gateway_payment_id, amount=None):
        """Refund a payment in Stripe."""
        if not self.secret_key:
            return {'error': 'Stripe not configured'}

        headers = {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        data = {'amount': amount} if amount else {}

        try:
            req = Request(
                f'{self.charges_url}/{gateway_payment_id}/refund',
                data=urlencode(data).encode('utf-8') if data else b'',
                headers=headers,
                method='POST'
            )
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return {
                    'id': result.get('id'),
                    'status': result.get('status'),
                    'amount': result.get('amount'),
                    'currency': result.get('currency')
                }
        except Exception as e:
            return {'error': str(e), 'code': 'UNKNOWN_ERROR'}

    def validate_webhook(self, payload, signature):
        """Validate Stripe webhook signature."""
        if not self.webhook_secret:
            return True  # Skip verification in dev mode
        try:
            return verify_webhook_signature(payload, signature, self.webhook_secret)
        except Exception:
            return False

    def format_gateway_response(self, gateway_response):
        """Format response for internal use."""
        return {
            'gateway': 'stripe',
            'gateway_id': gateway_response.get('id'),
            'status': gateway_response.get('status'),
            'created': gateway_response.get('created'),
            'success': gateway_response.get('status') == 'chargeable'
        }


class PagSeguroAdapter(GatewayAdapter):
    """PagSeguro payment gateway adapter."""

    def __init__(self):
        self.token = PAGSEGURO_TOKEN
        self.client_id = PAGSEGURO_CLIENT_ID
        self.base_url = 'https://api.pagseguro.com/v2'

    def create_charge(self, user_id, amount, currency='BRL', metadata=None):
        """Create a charge in PagSeguro."""
        if not self.token:
            return {'error': 'PagSeguro not configured', 'code': 'MISSING_CREDENTIALS'}

        # Convert BRL amount to cents (PagSeguro expects cents)
        amount_cents = int(round(amount * 100)) if amount > 0 else 100

        headers = {
            'Content-Type': 'application/json',
            'Authentication': f'Bearer {self.token}'
        }

        payload = {
            'items': [
                {
                    'id': f'order_{user_id}_{int(time.time())}',
                    'description': 'Serviço de pagamento',
                    'quantity': 1,
                    'amount': amount_cents,
                    'limit': 1
                }
            ],
            'sender': {
                'id': user_id
            },
            'shipping': {
                'address': {
                    'city': 'São Paulo',
                    'country': 'BRA',
                    'state': 'SP',
                    'cityName': 'São Paulo',
                    'postalCode': '01404001',
                    'recipientName': f'User {user_id}'
                }
            }
        }

        if metadata:
            payload['extra'] = {
                'metadata': metadata
            }

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
                    'amount': result.get('amount'),
                    'currency': result.get('currency'),
                    'qrCode': result.get('payments', {}).get('qrCode', {}).get('url'),
                    'copyAndPaste': result.get('payments', {}).get('copyAndPaste', {}).get('expirationDate')
                }
        except HTTPError as e:
            return {'error': f'PagSeguro HTTP error: {e.code}', 'code': 'HTTP_ERROR'}
        except URLError as e:
            return {'error': f'PagSeguro connection error: {e.reason}', 'code': 'CONNECTION_ERROR'}
        except Exception as e:
            return {'error': str(e), 'code': 'UNKNOWN_ERROR'}

    def get_payment_status(self, gateway_payment_id):
        """Get payment status from PagSeguro."""
        if not self.token:
            return {'error': 'PagSeguro not configured'}

        headers = {
            'Content-Type': 'application/json',
            'Authentication': f'Bearer {self.token}'
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
                    'amount': result.get('amount'),
                    'shippingStatus': result.get('shippingStatus'),
                    'paymentMethod': result.get('paymentMethod')
                }
        except Exception as e:
            return {'error': str(e), 'code': 'UNKNOWN_ERROR'}

    def refund(self, gateway_payment_id, amount=None):
        """Refund a payment in PagSeguro."""
        if not self.token:
            return {'error': 'PagSeguro not configured'}

        headers = {
            'Content-Type': 'application/json',
            'Authentication': f'Bearer {self.token}'
        }

        data = {'amount': amount} if amount else {}

        try:
            req = Request(
                f'{self.base_url}/refunds',
                data=json.dumps(data).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return {
                    'id': result.get('id'),
                    'status': result.get('status'),
                    'amount': result.get('amount')
                }
        except Exception as e:
            return {'error': str(e), 'code': 'UNKNOWN_ERROR'}

    def validate_webhook(self, payload, signature):
        """Validate PagSeguro webhook signature."""
        # PagSeguro uses a different signature scheme (X-Signature header)
        # This is a simplified version; production should verify against PagSeguro docs
        if not self.client_id:
            return True
        return True  # Placeholder - implement full verification in production

    def format_gateway_response(self, gateway_response):
        """Format response for internal use."""
        return {
            'gateway': 'pagseguro',
            'gateway_id': gateway_response.get('id'),
            'status': gateway_response.get('status'),
            'qrCode': gateway_response.get('qrCode'),
            'copyAndPaste': gateway_response.get('copyAndPaste'),
            'success': gateway_response.get('status') in ('approved', 'paid')
        }


class MercadoPagoAdapter(GatewayAdapter):
    """Mercado Pago payment gateway adapter."""

    def __init__(self):
        self.access_token = MERCADOPAGO_ACCESS_TOKEN
        self.base_url = 'https://api.mercadopago.com/v1'

    def create_charge(self, user_id, amount, currency='BRL', metadata=None):
        """Create a payment in Mercado Pago."""
        if not self.access_token:
            return {'error': 'Mercado Pago not configured', 'code': 'MISSING_CREDENTIALS'}

        # Format amount for Mercado Pago (in cents)
        amount_cents = int(round(amount * 100)) if amount > 0 else 100

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

        payload = {
            'transaction_amount': amount_cents,
            'currency_id': 'BRL',
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
        """Validate Mercado Pago webhook signature."""
        # Mercado Pago uses a different signature scheme (X-Signature header)
        # This is a simplified version; production should verify against Mercado Pago docs
        if not self.access_token:
            return True
        return True  # Placeholder - implement full verification in production

    def format_gateway_response(self, gateway_response):
        """Format response for internal use."""
        return {
            'gateway': 'mercadopago',
            'gateway_id': gateway_response.get('id'),
            'status': gateway_response.get('status'),
            'success': gateway_response.get('status') in ('approved', 'paid')
        }


# Factory to create gateway instances
GATEWAY_ADAPTERS = {}

def get_gateway_adapter(gateway='stripe'):
    """Factory to get payment gateway adapter."""
    if gateway not in GATEWAY_ADAPTERS:
        if gateway == 'stripe':
            GATEWAY_ADAPTERS[gateway] = StripeAdapter()
        elif gateway == 'pagseguro':
            GATEWAY_ADAPTERS[gateway] = PagSeguroAdapter()
        elif gateway == 'mercadopago':
            GATEWAY_ADAPTERS[gateway] = MercadoPagoAdapter()
        else:
            raise ValueError(f'Unknown gateway: {gateway}')
    
    return GATEWAY_ADAPTERS[gateway]


# Convenience functions for direct use
def create_charge(gateway='stripe', user_id=None, amount=None, **kwargs):
    """Create a charge using the specified gateway.
    
    Args:
        gateway: 'stripe', 'pagseguro', or 'mercadopago'
        user_id: User ID
        amount: Amount in BRL
        **kwargs: Additional metadata
    
    Returns:
        dict: Gateway response
    """
    adapter = get_gateway_adapter(gateway)
    return adapter.create_charge(user_id, amount, **kwargs)


def get_payment_status(gateway='stripe', gateway_payment_id=None):
    """Get status of a payment from a gateway."""
    adapter = get_gateway_adapter(gateway)
    return adapter.get_payment_status(gateway_payment_id)


def refund_payment(gateway='stripe', gateway_payment_id=None, amount=None):
    """Refund a payment using the gateway."""
    adapter = get_gateway_adapter(gateway)
    return adapter.refund(gateway_payment_id, amount)
