import torch
import warnings
warnings.filterwarnings("ignore")
import math
import sys
import time
import numpy as np
import torch
import utils
from sklearn.metrics import average_precision_score, confusion_matrix
import torchvision
import json
dic = json.load(open("dic.json","r"))
label_map = json.load(open("labels.json", "r"))

decode = {}
for k, v in label_map.items():
    decode[v] = k

def train_one_epoch(model, optimizer, data_loader, device, epoch, print_freq):
    model.train()
    metric_logger = utils.MetricLogger(delimiter="  ")
    metric_logger.add_meter("lr", utils.SmoothedValue(window_size=1, fmt="{value:.6f}"))
    header = f"Epoch: [{epoch}]"
    for param_group in optimizer.param_groups:
        param_group['lr'] = 0.001 * (0.95 ** epoch)

    for images, targets in metric_logger.log_every(data_loader, print_freq, header):
        images = list(image.to(device) for image in images)
        targets = [{k: v.to(device) for k, v in t.items()} for t in targets]
        loss_dict = model(images, targets)
        model.train()
        losses = sum(loss for loss in loss_dict.values())

        # reduce losses over all GPUs for logging purposes
        loss_dict_reduced = utils.reduce_dict(loss_dict)
        losses_reduced = sum(loss for loss in loss_dict_reduced.values())

        loss_value = losses_reduced.item()

        if not math.isfinite(loss_value):
            print(f"Loss is {loss_value}, stopping training")
            print(loss_dict_reduced)
            sys.exit(1)

        optimizer.zero_grad()
        losses.backward()
        optimizer.step()

        metric_logger.update(loss=losses_reduced, **loss_dict_reduced)
        metric_logger.update(lr=optimizer.param_groups[0]["lr"])
    
    return metric_logger

def _get_iou_types(model):
    model_without_ddp = model
    if isinstance(model, torch.nn.parallel.DistributedDataParallel):
        model_without_ddp = model.module
    iou_types = ["bbox"]
    if isinstance(model_without_ddp, torchvision.models.detection.MaskRCNN):
        iou_types.append("segm")
    if isinstance(model_without_ddp, torchvision.models.detection.KeypointRCNN):
        iou_types.append("keypoints")
    return iou_types

def evaluate(model, epoch, data_loader, device):
    device = torch.device('cuda:0') if torch.cuda.is_available() else torch.device('cpu')    
    model.eval()
    metric_logger = utils.MetricLogger(delimiter="  ")
    header = 'Test:'


    maskIOUs = {}
    IOUs = {}
    APs = {}
    accs = {}
    for images, targets in metric_logger.log_every(data_loader, 100, header):
        images = list(img.to(device) for img in images)
        preds = model(images)
        for i, image in enumerate(images):
            pred = preds[i]
            boxes = pred['boxes'].detach().cpu()
            labels = pred['labels'].detach().cpu()
            scores = pred['scores'].detach().cpu()
            masks = pred['masks'].detach().cpu()

            if len(labels) == 0: # if no label, nothing to evaluate	
                continue	

          
            target = targets[i]
            gt_boxes = target['boxes']
            gt_labels = target['labels']
            gt_masks = target['masks']
            gt_label = gt_labels[0].item()
            class_name = decode[gt_label]
 
            
            pred_result = {}
            for j, label in enumerate(labels):
                label = label.item()

                if label in pred_result:
                    pred_result[label]['scores'].append(float(scores[j]))
                    pred_result[label]['boxes'].append(boxes[j])
                    pred_result[label]['masks'].append(masks[j])
                else:
                    pred_result[label]={'scores':[float(scores[j])], 'boxes':[boxes[j]], 'masks':[masks[j]]}
            

            for label, output in pred_result.items():
                N = len(output['scores'])
                temp_boxes = torch.zeros((N, 4))                
                temp_masks = torch.zeros((N, 480, 360), dtype=torch.bool)

                for k, box in enumerate(output['boxes']):
                    temp_boxes[k, :] = box
                for k, mask in enumerate(output['masks']):
                    temp_masks[k, :, :] = mask.bool()

                pred_result[label]['boxes'] = temp_boxes
                pred_result[label]['masks'] = temp_masks
                
            for j, (label, output) in enumerate(pred_result.items()):
                temp_boxes = [gt_box for gt_box, gt_label in zip(gt_boxes, gt_labels) if label == gt_label]
                if not temp_boxes:
                    continue
                
                gt_label_boxes = torch.zeros((len(temp_boxes), 4))
                for k, box in enumerate(temp_boxes):
                    gt_label_boxes[k, :] = box

                box_iou = torchvision.ops.box_iou(output['boxes'], gt_label_boxes)

                box_iou_d1 = torch.max(box_iou, dim=1)
                pred_classes = []
                 
                for temp_iou in box_iou_d1.values:
                    #for temp_iou in iou:
                    temp_iou = float(temp_iou)
                    if temp_iou > 0.3:
                        pred_classes.append(True)
                        if label in IOUs:
                            IOUs[label].append(temp_iou)
                        else:
                            IOUs[label] = [temp_iou]

                    else:
                        pred_classes.append(False)

                AP = average_precision_score(pred_classes, output['scores'])
                if not np.isnan(AP):
                    if label in APs:
                        APs[label].append(AP)
                    else:
                        APs[label] = [AP]

                if not pred_classes:
                    acc = 0
                else:
                    acc = sum([int(correct) for correct in pred_classes])/len(pred_classes)

                if label in accs:
                    accs[label].append(acc)
                else:
                    accs[label] = [acc]

                
                temp_masks = [gt_mask for gt_mask, gt_label in zip(gt_masks, gt_labels) if label == gt_label]
                
                for mask in temp_masks:
                    mask = mask.bool().numpy()
                    for gt_mask in output['masks'].numpy():
                        intersection = np.logical_and(mask, gt_mask)
                        union = np.logical_or(mask, gt_mask)

                        iou_score = np.sum(intersection) / np.sum(union)
                        if iou_score > 0.2:
                            if label in maskIOUs:
                                maskIOUs[label].append(iou_score)
                           
                            else:
                                maskIOUs[label] = [iou_score]

    mean_maskIOU = {decode[int(k)]:np.mean(v) for k, v in maskIOUs.items()}
    mIOU = {decode[int(k)]:np.mean(v) for k, v in IOUs.items()}
    mAP = {decode[int(k)]:np.mean(v) for k, v in APs.items()}
    meanAcc = {decode[int(k)]:np.mean(v) for k, v in accs.items()}
    
    metrics = {"mIOU": mIOU, "mAP": mAP, "meanAcc":meanAcc, "mean_maskIOU":mean_maskIOU}
    import json
    with open(f"metrics_{epoch}.json", "w") as f:
        json.dump(metrics, f)
    del metrics

    
    # gather the stats from all processes
    metric_logger.synchronize_between_processes()

