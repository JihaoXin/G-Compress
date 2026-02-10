"""
Simplified evaluate_utils without lm_eval dependency.
Only includes evaluate_perplexity function.
"""
import torch
import torch.nn as nn
from tqdm import tqdm


@torch.no_grad()
def evaluate_perplexity(model, dataset, limit):
    """
    Evaluate perplexity on a dataset.

    Args:
        model: The language model
        dataset: input ids tensor of shape [batch, sequence length]
        limit: maximum number of samples to evaluate

    Returns:
        PPL value (float)
    """
    nsamples, seqlen = dataset.size()

    nlls = []

    for i in range(nsamples):
        if i == limit:
            break
        input_ids = dataset[i : i + 1, :-1].to(model.device)
        labels = dataset[i : i + 1, 1:].contiguous()
        logits = model(input_ids=input_ids)[0]
        shift_logits = logits[:, :, :]
        shift_labels = labels.to(model.device)
        loss_fct = nn.CrossEntropyLoss()
        loss = loss_fct(
            shift_logits.view(-1, shift_logits.size(-1)),
            shift_labels.view(-1),
        )
        neg_log_likelihood = loss.float() * seqlen
        nlls.append(neg_log_likelihood)

    ppl = torch.exp(torch.stack(nlls).sum() / (len(nlls) * seqlen))
    return ppl.item()
