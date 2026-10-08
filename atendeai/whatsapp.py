"""Cliente da WhatsApp Cloud API. Nenhuma repetição automática de envios."""
import httpx
import re


class WhatsAppRejected(Exception):
    pass


class WhatsAppUncertain(Exception):
    pass


class WhatsAppClient:
    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport

    def send(self, payload):
        if not self.settings.whatsapp_ready:
            raise WhatsAppRejected("Configure e habilite a WhatsApp Cloud API antes de enviar.")
        url = f"https://graph.facebook.com/{self.settings.whatsapp_api_version}/{self.settings.whatsapp_phone_number_id}/messages"
        try:
            with httpx.Client(timeout=20, transport=self.transport, follow_redirects=False) as client:
                response = client.post(url, json=payload,
                                       headers={"Authorization": "Bearer " + self.settings.whatsapp_token})
        except httpx.HTTPError:
            raise WhatsAppUncertain("O resultado do envio é incerto. Não houve repetição automática.") from None
        if 400 <= response.status_code < 500:
            try:
                code = str(response.json().get("error", {}).get("code", ""))[:40]
                if not re.fullmatch(r"[0-9]{1,20}", code):
                    code = ""
            except (ValueError, AttributeError):
                code = ""
            raise WhatsAppRejected(f"Meta recusou o envio (HTTP {response.status_code}, código {code}).")
        if not 200 <= response.status_code < 300:
            raise WhatsAppUncertain("Resposta inconclusiva da Meta. Confira a entrega antes de qualquer novo envio.")
        try:
            message_id = response.json()["messages"][0]["id"]
            if not isinstance(message_id, str) or not 1 <= len(message_id) <= 250:
                raise ValueError()
        except (ValueError, KeyError, IndexError, TypeError):
            raise WhatsAppUncertain("A Meta não retornou o identificador da mensagem; envio não repetido.") from None
        return message_id
