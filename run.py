from tqdm import tqdm
import torch
import torchvision
import torch.nn.functional as F
import os
import numpy as np
from utils import *
from modules import *
import wandb
import hydra
from omegaconf import OmegaConf, DictConfig


def train_network(
    batch_size=256,
    dataset="MNIST",
    device="cuda",
    bias=True,
    decorrelation_method="copi",
    decor_lr=1e-3,
    n_hidden_layers=3,
    hidden_layer_size=1000,
    loss_func_type="CCE",  # "MSE"
    optimizer_type="Adam",
    fwd_lr=1e-2,
    seed=42,
    nb_epochs=10,
    loud=True,
    wandb=None,
):

    betas = [0.9, 0.999]
    eps = 1e-8

    # Initializing random seeding
    torch.manual_seed(seed)
    np.random.seed(seed)

    # Load dataset
    tv_dataset = dataset
    if dataset == "MNIST":
        tv_dataset = torchvision.datasets.MNIST
    elif dataset == "CIFAR10":
        tv_dataset = torchvision.datasets.CIFAR10
    elif dataset == "CIFAR100":
        tv_dataset = torchvision.datasets.CIFAR100

    # layer_mapping = {
    #     "NP": NPLinear,
    #     "WP": WPLinear,
    #     "NTWP": NTWPLinear,
    #     "BP": BPLinear,
    # }
    layer_type = BPLinear

    train_loader, test_loader = construct_dataloaders(
        tv_dataset, batch_size=batch_size, device=device
    )

    # If dataset is CIFAR, change input shape
    in_size = 28 * 28
    out_size = 10
    if tv_dataset == torchvision.datasets.CIFAR10:
        in_size = 32 * 32 * 3
    if tv_dataset == torchvision.datasets.CIFAR100:
        in_size = 32 * 32 * 3
        out_size = 100
    if tv_dataset == "TIN":
        in_size = 64 * 64 * 3
        out_size = 200

    # Initialize model
    model = DecorNet(
        in_size=in_size,
        out_size=out_size,
        n_hidden_layers=n_hidden_layers,
        hidden_size=hidden_layer_size,
        layer_type=layer_type,
        decorrelation=decor_lr,
        decorrelation_method=decorrelation_method,
        biases=bias,
    )
    model.to(device)

    # Initialize metric storage
    metrics = init_metric()

    # Define optimizers
    fwd_optimizer = None
    if optimizer_type == "Adam":
        fwd_optimizer = torch.optim.Adam(
            model.get_fwd_params(),
            betas=betas,
            eps=eps,
            lr=fwd_lr,
        )
    elif optimizer_type == "SGD":
        fwd_optimizer = torch.optim.SGD(model.get_fwd_params(), lr=fwd_lr)

    optimizers = [fwd_optimizer]
    if decorrelation_method is not None:
        decor_optimizer = torch.optim.SGD(model.get_decor_params(), lr=decor_lr)
        optimizers.append(decor_optimizer)

    loss_func = None
    if loss_func_type == "CCE":
        loss_obj = torch.nn.CrossEntropyLoss(reduction="none")
        loss_func = lambda input, target, onehot: loss_obj(input, target)
    elif loss_func_type == "MSE":
        loss_obj = torch.nn.MSELoss(reduction="none")
        loss_func = lambda input, target, onehot: torch.sum(
            loss_obj(input, onehot), axis=1
        )

    # Train loop
    for e in tqdm(range(nb_epochs + 1), disable=not loud):
        metrics = update_metrics(
            model,
            metrics,
            device,
            "train",
            train_loader,
            loss_func,
            e,
            loud=loud,
            wandb=wandb,
        )
        metrics = update_metrics(
            model,
            metrics,
            device,
            "test",
            test_loader,
            loss_func,
            e,
            loud=False,
            wandb=wandb,
        )
        if e < nb_epochs:
            train(model, device, train_loader, optimizers, e, loss_func, loud=False)
        if np.isnan(metrics["test"]["loss"][-1]) or np.isnan(
            metrics["train"]["loss"][-1]
        ):
            print("NaN detected, aborting training")
            break
    return metrics


@hydra.main(version_base="1.3", config_path="conf/", config_name="config")
def run(config: DictConfig) -> None:
    cfg = OmegaConf.to_container(config, resolve=True, throw_on_missing=True)
    wandb.init(
        config=cfg,
        entity=config.wandb.entity,
        project=config.wandb.project,
        mode=config.wandb.mode,
    )

    if config.decorrelation_method == "None":
        config.decorrelation_method = None

    # For now foldiak is too slow unfortunately
    if config.decorrelation_method == "foldiak":
        exit()

    metrics = train_network(
        batch_size=config.batch_size,
        dataset=config.dataset,
        device=config.device,
        bias=config.bias,
        decorrelation_method=config.decorrelation_method,
        decor_lr=config.decor_lr,
        n_hidden_layers=config.n_hidden_layers,
        hidden_layer_size=config.hidden_layer_size,
        loss_func_type=config.loss_func_type,
        optimizer_type=config.optimizer_type,
        fwd_lr=config.fwd_lr,
        seed=config.seed,
        nb_epochs=config.nb_epochs,
        loud=config.loud,
        wandb=wandb,
    )

    print(metrics)


if __name__ == "__main__":
    run()
