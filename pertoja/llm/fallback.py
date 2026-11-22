"""Respostas offline determinísticas locais para suporte e geração de anúncios."""

from __future__ import annotations

import math
import re
from typing import Any

from pertoja.llm.prompts import _get_field, sanitize_history

_MATH_EXPR_RE = re.compile(
    r"^\s*(?:(?:quanto\s+(?:é|e|da|dá|fica|vale)|calcule|calc|qual\s+(?:é|e)\s+o\s+resultado\s+de)\s*)?"
    r"(-?\d+(?:[.,]\d+)?)\s*([+\-*/x×÷])\s*(-?\d+(?:[.,]\d+)?)\s*\??\s*$",
    re.IGNORECASE,
)

_DISPUTE_INTENT_RE = re.compile(
    r"\b(?:"
    r"n[aã]o\b.{0,28}\b(?:liberar|confirmar\s+conclus[aã]o|pagar)"
    r"|(?:evitar|impedir|bloquear|reter|segurar|travar|recusar)\b.{0,28}\b(?:pagamento|libera[cç][aã]o|repasse|escrow|conclus[aã]o)"
    r"|disputa|contestar|contesta[cç][aã]o|media[cç][aã]o|estorno|reembolso|devolu[cç][aã]o"
    r"|mal\s+feito|servi[cç]o\s+ruim|n[aã]o\s+gostei|nao\s+gostei|incompleto"
    r"|n[aã]o\s+concluiu|nao\s+concluiu|dinheiro\s+de\s+volta"
    r")\b",
    re.IGNORECASE,
)


def _try_safe_arithmetic(message: str) -> str | None:
    match = _MATH_EXPR_RE.match(message or "")
    if not match:
        return None
    raw_a, op, raw_b = match.groups()
    try:
        a = float(raw_a.replace(",", "."))
        b = float(raw_b.replace(",", "."))
    except ValueError:
        return None
    if not (math.isfinite(a) and math.isfinite(b)) or abs(a) > 1e12 or abs(b) > 1e12:
        return None

    op_low = op.lower()
    if op_low == "+":
        res = a + b
    elif op_low == "-":
        res = a - b
    elif op_low in ("*", "x", "×"):
        res = a * b
    elif op_low in ("/", "÷"):
        if b == 0:
            return (
                "Não é possível dividir por zero! "
                "(Estou respondendo em modo offline, pois a IA principal não está conectada no momento.)"
            )
        res = a / b
    else:
        return None

    if not math.isfinite(res):
        return None
    formatted = str(int(round(res))) if abs(res - round(res)) < 1e-9 else f"{res:.4f}".rstrip("0").rstrip(".")
    return (
        f"{formatted}! "
        "(Aviso: estou no modo offline com FAQ local porque a IA principal está indisponível no momento — "
        "se precisar de ajuda com pedidos, Escrow, disputas ou PIN no PertoJá, é só perguntar.)"
    )


def _is_simple_greeting(msg_lower: str) -> bool:
    cleaned = re.sub(r"[!.,;?😄🙂👋🙏]+", " ", msg_lower).strip()
    greetings = {
        "oi",
        "olá",
        "ola",
        "e ai",
        "e aí",
        "opa",
        "hey",
        "hello",
        "hi",
        "bom dia",
        "boa tarde",
        "boa noite",
        "tudo bem",
        "tudo bom",
        "oi tudo bem",
        "olá tudo bem",
        "ola tudo bem",
        "bom dia tudo bem",
        "boa tarde tudo bem",
        "boa noite tudo bem",
    }
    return cleaned in greetings


def _is_simple_thanks_or_bye(msg_lower: str) -> bool:
    cleaned = re.sub(r"[!.,;?😄🙂👋🙏]+", " ", msg_lower).strip()
    thanks = {
        "obrigado",
        "obrigada",
        "muito obrigado",
        "muito obrigada",
        "valeu",
        "vlw",
        "brigado",
        "brigada",
        "agradeço",
        "agradeco",
        "tchau",
        "até mais",
        "ate mais",
        "flw",
        "ok obrigado",
        "ok obrigada",
        "show obrigado",
        "perfeito obrigado",
    }
    return cleaned in thanks


def _word_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9à-ú]{3,}", (text or "").lower()))


def _is_repeating_previous_turn(
    candidate_reply: str,
    user_message: str,
    clean_history: list[dict[str, str]],
) -> bool:
    if not clean_history:
        return False

    last_assistant = ""
    last_user = ""
    for item in reversed(clean_history):
        if not last_assistant and item["role"] == "assistant":
            last_assistant = item["content"]
        elif not last_user and item["role"] == "user":
            last_user = item["content"]
        if last_assistant and last_user:
            break

    if not last_assistant:
        return False

    norm_cand = re.sub(r"\s+", " ", candidate_reply.strip().lower())
    norm_prev = re.sub(r"\s+", " ", last_assistant.strip().lower())
    if norm_cand == norm_prev:
        return True

    cand_tokens = _word_tokens(candidate_reply)
    prev_tokens = _word_tokens(last_assistant)
    if cand_tokens and prev_tokens:
        jaccard = len(cand_tokens & prev_tokens) / len(cand_tokens | prev_tokens)
        if jaccard >= 0.72:
            return True

    if last_user:
        norm_u1 = re.sub(r"[^\wà-ú]+", " ", user_message.lower()).strip()
        norm_u2 = re.sub(r"[^\wà-ú]+", " ", last_user.lower()).strip()
        if norm_u1 and norm_u1 == norm_u2:
            return True

    return False


def _offline_reason_note(reason: str) -> str:
    if reason == "localhost_in_serverless":
        return (
            "A IA principal está em modo offline (o gateway localhost configurado não é acessível "
            "na Vercel sem uma chave de API oficial/cloud configurada)."
        )
    if reason == "rate_limited":
        return "A IA principal atingiu temporariamente o limite de requisições e entrou em modo offline."
    if reason == "auth_error":
        return "A IA principal está em modo offline porque a credencial do provedor precisa de revisão."
    if reason in ("timeout", "connection_error"):
        return "A IA principal não respondeu a tempo no momento, então estou operando em modo offline (FAQ local)."
    return "A IA principal não está conectada no momento, então estou operando em modo offline (FAQ local)."


def _build_antirepeat_followup(category: str) -> str:
    if category == "dispute":
        return (
            "Passo a passo prático na tela para reter o pagamento em Escrow: "
            '1) Abra o Portal do Cliente e localize o card do pedido em "Meus Pedidos". '
            '2) NÃO clique em "Confirmar Conclusão" nem em "Confirmar e Liberar Escrow". '
            '3) Clique no botão "Abrir Disputa" ("Abrir Mediação / Disputa") no card do pedido dentro '
            'da janela de 48h, descreva o motivo e anexe evidências (como mensagens do "Chat do Pedido"). '
            'O status mudará para "em_disputa", travando o repasse até a decisão da mediação.'
        )
    if category == "cancel":
        return (
            "Na prática, para agir agora sobre atraso ou cancelamento: abra o card do pedido no Portal do Cliente, "
            'verifique o status atual e utilize o "Chat do Pedido" para registrar o ocorrido. '
            'Se o pedido ainda não estiver em execução, você pode cancelar pelo painel; se já estiver "em_execucao" '
            'e pago, use "Abrir Mediação / Disputa" para garantir a análise do estorno.'
        )
    if category == "faq":
        return (
            "Para navegar rápido na plataforma: no Portal do Cliente você acompanha status, PIN de 4 dígitos, "
            "botões de confirmação/disputa do Escrow e SOS Emergência diretamente no card de cada pedido; "
            'no Portal do Prestador você gerencia anúncios (incluindo "Gerar com IA"), valida o PIN na chegada e '
            "acompanha saldo retido e plano Básico/Pro na aba financeira."
        )
    if category == "greeting":
        return (
            "Continuo por aqui no modo offline (FAQ local). Me diga qual dúvida específica você tem "
            "(por exemplo: segurar pagamento no Escrow, abrir disputa, PIN de 4 dígitos, KYC ou planos)!"
        )
    return (
        "Como sigo em modo offline (FAQ local) sem acesso ao modelo de IA generativa, não consigo responder "
        "perguntas livres fora das regras do PertoJá. Posso te orientar imediatamente sobre: "
        "não liberar pagamento / disputa no Escrow 48h, cancelamento, PIN de 4 dígitos, KYC Tier 1/2, "
        "planos Básico/Pro, SOS Emergência e LGPD."
    )


def _build_faq_topics(msg_lower: str) -> list[str]:
    topics: list[str] = []
    if any(
        k in msg_lower
        for k in (
            "pagamento",
            "pagar",
            "pix",
            "cartão",
            "cartao",
            "boleto",
            "escrow",
            "garantia",
            "repasse",
            "recebo",
            "receber",
            "48h",
            "custódia",
            "custodia",
        )
    ):
        topics.append(
            "Pagamentos & Escrow: Pagamentos via PIX, Cartão ou Boleto ficam protegidos em "
            "custódia (Escrow) durante o serviço e por 48h após a conclusão antes do repasse ao "
            'prestador (se precisar contestar antes da liberação, clique em "Abrir Mediação / Disputa").'
        )
    if any(
        k in msg_lower
        for k in (
            "pin",
            "código",
            "codigo",
            "porta",
            "check-in",
            "checkin",
            "iniciar",
            "execução",
            "execucao",
            "chegada",
        )
    ):
        topics.append(
            "Check-in com PIN: O prestador só inicia a execução após validar na porta o PIN de "
            "4 dígitos exibido no painel do cliente (limite de 5 tentativas)."
        )
    if any(
        k in msg_lower
        for k in (
            "kyc",
            "verificação",
            "verificacao",
            "documento",
            "crea",
            "cft",
            "crt",
            "nr-10",
            "nr10",
            "cau",
            "selo",
            "tier",
        )
    ):
        topics.append(
            "Verificação KYC: Contamos com KYC Tier 1 (documento oficial e selfie) e Tier 2 "
            "obrigatório para categorias técnicas (Elétrica e Encanamento) mediante registro "
            "CREA, CFT, CRT, NR-10 ou CAU."
        )
    if any(
        k in msg_lower
        for k in (
            "plano",
            "planos",
            "taxa",
            "comissão",
            "comissao",
            "básico",
            "basico",
            "pro",
            "1800",
            "1.800",
            "isenção",
            "isencao",
            "mensalidade",
        )
    ):
        topics.append(
            "Planos para Prestadores: O Plano Básico tem taxa de 12% (com isenção até "
            "R$ 1.800/mês) e o Plano Pro reduz a taxa para 8% com destaque nas buscas."
        )
    if any(
        k in msg_lower
        for k in ("sos", "emergência", "emergencia", "segurança", "seguranca", "denúncia", "denuncia", "rota", "190")
    ):
        topics.append(
            "Segurança & SOS: Em pedidos ativos você conta com botão SOS Emergência (em risco "
            "imediato ligue 190), compartilhamento de rota verificada e suporte a disputas."
        )
    if any(
        k in msg_lower
        for k in (
            "avaliação",
            "avaliacao",
            "avaliar",
            "review",
            "nota",
            "estrela",
            "double-blind",
            "lgpd",
            "privacidade",
            "dados",
            "excluir conta",
            "anonimização",
            "anonimizacao",
        )
    ):
        topics.append(
            "Avaliações & LGPD: As avaliações são double-blind (publicadas após ambas as partes "
            "avaliarem ou após 7 dias) e seus dados seguem rigorosamente a LGPD."
        )
    if any(
        k in msg_lower
        for k in (
            "anúncio",
            "anuncio",
            "descrição",
            "descricao",
            "criar serviço",
            "criar servico",
            "cadastrar serviço",
            "cadastrar servico",
            "gerar com ia",
        )
    ):
        topics.append(
            "Anúncios: No Portal do Prestador, informe título, categoria e preço e use "
            '"Gerar com IA" (ou preencha manualmente) para criar a descrição do serviço.'
        )
    return topics


def fallback_chat_support_reply(
    message: str,
    context_text: str = "",
    history: Any = None,
    user_info: Any = None,
    reason: str = "unconfigured",
) -> str:
    """Resposta local determinística quando nenhum provedor LLM está disponível."""
    _ = context_text
    raw_msg = str(message or "").strip()
    msg_lower = raw_msg.lower()
    clean_history = sanitize_history(history)

    first_name = ""
    if user_info is not None:
        full_name = str(_get_field(user_info, "nome", "") or "").strip()
        if full_name:
            first_name = full_name.split()[0]

    if _DISPUTE_INTENT_RE.search(msg_lower):
        category = "dispute"
        reply = (
            "Se você NÃO quiser liberar o pagamento (por serviço incompleto, mal feito, divergência ou "
            'ausência do prestador), NÃO clique em "Confirmar Conclusão" nem em "Confirmar e Liberar Escrow". '
            'Em vez disso, clique em "Abrir Disputa" ("Abrir Mediação / Disputa") no card do pedido no '
            "Portal do Cliente dentro da janela de 48h do Escrow, informando o motivo e as evidências. "
            "Isso muda imediatamente o status e o escrow_status do pedido para em_disputa, congelando o "
            "repasse ao prestador até a mediação da equipe (que pode decidir por estorno total, parcial ou "
            "liberação). Atenção: se não houver confirmação nem disputa aberta em 48h, o Escrow libera automaticamente."
        )
    elif any(
        k in msg_lower
        for k in (
            "cancelar",
            "cancelamento",
            "atraso",
            "atrasou",
            "não apareceu",
            "nao apareceu",
            "não veio",
            "nao veio",
            "no-show",
            "desistir",
            "desistência",
            "desistencia",
        )
    ):
        category = "cancel"
        reply = (
            "Sobre cancelamentos e atrasos no PertoJá: se o prestador cancelar ou não comparecer (no-show), "
            "você recebe estorno integral (100%) do valor protegido em Escrow. "
            "Se você cancelar antes do deslocamento, o estorno também é total; após o prestador ficar "
            "em_transito, há retenção de 20% (limitada a R$ 40,00) como taxa de deslocamento. "
            'Se o pedido já estiver em_execucao e pago, abra uma mediação clicando em "Abrir Mediação / Disputa" no card.'
        )
    elif _is_simple_greeting(msg_lower):
        category = "greeting"
        saudacao = f"Oi, {first_name}!" if first_name else "Oi!"
        reply = (
            f"{saudacao} Como posso te ajudar hoje no PertoJá? "
            "(Obs.: estou no modo offline com FAQ local, mas posso orientar sobre Escrow 48h, "
            "disputas, cancelamento, PIN na porta, KYC, planos e SOS.)"
        )
    elif _is_simple_thanks_or_bye(msg_lower):
        category = "greeting"
        reply = "Por nada! Se precisar de mais alguma orientação sobre pedidos ou regras do PertoJá, estou por aqui."
    else:
        math_reply = _try_safe_arithmetic(raw_msg)
        if math_reply is not None:
            category = "math"
            reply = math_reply
        else:
            topics = _build_faq_topics(msg_lower)
            if topics:
                category = "faq"
                reply = " ".join(topics) + " (Respondido via FAQ local em modo offline.)"
            else:
                category = "unknown"
                reply = (
                    f"{_offline_reason_note(reason)} "
                    "Por isso, não consigo responder perguntas livres fora do FAQ do PertoJá agora. "
                    "No modo offline posso ajudar na hora com: "
                    "Escrow 48h e como não liberar pagamento / abrir disputa, cancelamentos, "
                    "check-in com PIN de 4 dígitos, verificação KYC (CREA/CFT/NR-10/CAU), "
                    "planos Básico e Pro, SOS Emergência e LGPD."
                )

    if _is_repeating_previous_turn(reply, raw_msg, clean_history):
        return _build_antirepeat_followup(category)
    return reply


def fallback_ad_description(
    title: str,
    category: str = "",
    description: str = "",
    price: Any = None,
    service_type: str = "",
    extra: str = "",
) -> str:
    """Gera localmente uma descrição comercial objetiva (<= 280 chars) preservando título e preço."""
    clean_title = str(title or "").strip()
    clean_cat = str(category or "").strip()
    clean_desc = str(description or "").strip()
    clean_type = str(service_type or "").strip()
    clean_extra = str(extra or "").strip()

    price_str = ""
    if price is not None and price != "":
        try:
            p_val = float(price)
            if math.isfinite(p_val) and p_val > 0:
                price_str = f"R$ {p_val:.2f}".replace(".", ",")
        except (TypeError, ValueError):
            price_str = ""

    header = clean_title
    if clean_cat and clean_cat.lower() not in clean_title.lower():
        header = f"{clean_title} ({clean_cat})"

    segments = [f"{header}: atendimento profissional com qualidade, pontualidade e garantia pelo PertoJá."]

    if clean_desc:
        segments.append(clean_desc.rstrip(".") + ".")
    if clean_extra and clean_extra.lower() not in clean_desc.lower():
        segments.append(clean_extra.rstrip(".") + ".")

    meta: list[str] = []
    if clean_type:
        meta.append(f"Modalidade: {clean_type}")
    if price_str:
        meta.append(f"Valor: {price_str}")
    if meta:
        segments.append(" | ".join(meta) + ".")

    segments.append("Agende já com segurança!")
    result = " ".join(segments).strip()

    if len(result) <= 280:
        return result

    if price_str:
        compact_meta = f"Valor: {price_str}."
        if clean_type:
            candidate_meta = f"Modalidade: {clean_type} | Valor: {price_str}."
            if len(header) + len(candidate_meta) + 40 <= 280:
                compact_meta = candidate_meta
        compact = f"{header}: atendimento profissional pelo PertoJá. {compact_meta} Agende já!"
        if len(compact) <= 280:
            if clean_desc:
                budget = 280 - len(compact) - 2
                if budget >= 20:
                    desc_cut = clean_desc[:budget].rstrip(" .,;:-") + "."
                    return f"{header}: {desc_cut} {compact_meta} Agende já!"[:280]
            return compact

    return result[:277].rstrip(" ,;:-") + "..."
